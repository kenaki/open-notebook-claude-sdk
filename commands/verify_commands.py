"""
Vision verify-clean commands for Open Notebook (Track B, Chunk B2).

Renders the physical PDF pages of a single ``source_section`` as ground-truth
images, feeds them (plus the machine-parsed ``content``) to the deployed vision
model, and writes a corrected ``cleaned_content`` back onto the section —
**never** touching the immutable raw parse (``source_section.content`` or
``Source.full_text``, Decision #5).

Two commands:
  - ``verify_clean_section`` : per-section verify-clean (one section per job so the
    model's context resets between chapters by design).
  - ``verify_clean_source``  : fan-out orchestrator — one ``verify_clean_section``
    job per LEAF section of a source (leaves partition the document; proofing
    parent nodes too re-emitted the book 2.6× over — to-fix/004 Finding 1).
    Wrapped per-section so one section's submit failure can't poison the rest.

Design notes:
  - Decision #6: uses the configured ``default_vision_model`` (deployed Ollama
    Qwen). If unconfigured / misconfigured we skip gracefully (cleaned_content
    left None) rather than crashing — the text-only fallback is a follow-up.
  - Decision #8: page indices are physical (0-based) everywhere; ``page_offset``
    is applied ONLY to compute display page labels in the prompt, never for
    slicing.
  - B1 pilot: this thinking-capable vision model silently returns empty content
    when ``max_tokens`` is unset — we pass ``max_tokens=8192`` explicitly
    (mandatory). Low-confidence output is rejected rather than blind-overwriting
    anything.
  - to-fix/004 Finding 2: output that is implausibly shorter than the input
    (length-stop or below ``_MIN_CLEANED_RATIO``) is REJECTED — recorded, never
    written — because every reader prefers ``cleaned_content`` over the raw
    parse, so a truncated proof silently shortens the chapter everywhere.

Where the verdict goes (migration 27). Every outcome here is a *diagnostic about
how well we parsed the book*, never *content of the book*, so none of it may
reach an LLM. It used to: these were written as ``verify_flag`` source insights,
and ``Notebook.get_context()`` injects every insight into the prompt verbatim and
uncapped (~114K chars on a 472-section textbook) while ``create_insight_command``
embeds each one into vector search. Now:
  - the per-section verdict lands on ``source_section.verify_status`` /
    ``verify_reason`` — queryable, badgeable, and structurally unreachable from
    the prompt because ``get_outline()`` selects an explicit column list;
  - a human-readable copy lands on the job's own event log as a ``warning``
    event, visible in the agent console at /activity;
  - the vision model's freeform discrepancy narration — the bulk of the old
    volume, and the least actionable part of it — is logged and dropped.
"""
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command, submit_command

from commands._heavy_lane import heavy_lane, heavy_lane_for
from commands._job_guards import (
    MAX_REQUEUES,
    blocks_in_flight,
    chaptering_in_flight,
    is_resource_busy,
    requeue_job,
    section_is_gone,
    siblings_in_flight,
    submit_command_once,
)
from open_notebook.ai.models import model_manager
from open_notebook.ai.provision import apply_reasoning_flag
from open_notebook.ai.vision_utils import provision_vision_message
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Source, SourceSection
from open_notebook.exceptions import ConfigurationError, NotFoundError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.job_progress import report_job_progress, report_job_warning
from open_notebook.utils.text_utils import extract_text_content


def _job_id(input_data: CommandInput) -> Optional[str]:
    """Extract this command's own record id for progress/event reporting
    (mirrors the ``execution_context.command_id`` pattern used across
    ``commands/*``). ``None`` when run outside a tracked job (e.g. tests)."""
    return (
        str(input_data.execution_context.command_id)
        if input_data.execution_context
        else None
    )

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Render at 2x zoom (~144 DPI) so dense textbook body text / tables stay legible
# to the vision model. Cost/latency are not a constraint (local GPU; North star
# = fidelity).
_RENDER_ZOOM = 2.0

# Defensive guard: a pathological "single section spanning the whole document"
# (headingless PDF that fell back to one section in A3) would otherwise render
# hundreds of page images into one vision call and blow the context window. When
# a section exceeds this many pages we SKIP the vision pass and record a
# 'skipped' verdict rather than truncating (truncation would silently drop content).
# Real chapters are comfortably under this bound.
_MAX_VERIFY_PAGES = 50

# Output-sanity floor (to-fix/004 Finding 2): verify must not shrink a section.
# The prompt forbids paraphrase/summary, so legitimate proofs come back at
# ~100-177% of the raw parse (repairing hyphenation/tables adds characters). A
# reply much shorter than the input means the model truncated (hit max_tokens)
# or quietly summarized — observed live: a 22,532-char Preface "proofed" down to
# 506 chars and every reader silently preferred it. Below this ratio the proof
# is rejected: cleaned_content stays unset and verify_status='rejected' records why.
_MIN_CLEANED_RATIO = 0.8

# Context window for the vision call. Esperanto's ChatOllama wrapper defaults
# num_ctx to 8192, which doesn't even hold the OUTPUT budget (max_tokens=8192)
# plus a one-page prompt (~2.6K tokens observed) — Ollama then silently rolls
# the window during generation. 32K covers the largest verifiable leaf
# (~14K tokens of text + a handful of page images + the 8K reply).
_VERIFY_NUM_CTX = 32768

# Instruction handed to the vision model alongside the page images + parsed text.
_VERIFY_INSTRUCTION = (
    "Fix parser artifacts (column merges, header/footer interleaving, "
    "hyphenation, broken tables, math). Do NOT paraphrase or summarize. "
    "Preserve all content. Flag any unreconcilable discrepancies at the end "
    "under a 'DISCREPANCIES:' header."
)


# ---------------------------------------------------------------------------
# Pydantic I/O models
# ---------------------------------------------------------------------------


class VerifyCleanSectionInput(CommandInput):
    source_section_id: str
    # Declared (not just passed) so it PERSISTS into the command row's args.
    # Undeclared keys are dropped, which is why cancel_source_jobs could never
    # see per-section jobs, and why the phase chain below can't count siblings
    # without it.
    source_id: Optional[str] = None
    # Stamped by verify_clean_source at fan-out time from source.parse_generation.
    # A newer generation means build_blocks has since rebuilt the section tree
    # and this job's section id belongs to a dead generation. None = unstamped
    # (manual re-run, or a source that never went through build_blocks) → run.
    parse_generation: Optional[int] = None
    # Incremented each time the job is requeued for a busy heavy slot.
    requeue_count: int = 0


class VerifyCleanSectionOutput(CommandOutput):
    cleaned_content: Optional[str] = None
    discrepancies: Optional[str] = None


class VerifyCleanSourceInput(CommandInput):
    source_id: str


class VerifyCleanSourceOutput(CommandOutput):
    success: bool
    source_id: str
    sections_found: int = 0
    jobs_submitted: int = 0
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_pdf_path(source: Source) -> Optional[str]:
    """Return an existing on-disk .pdf path for the source, else None.

    Reuses the exact file-resolution pattern from
    ``commands/section_commands.py`` (asset.file_path → Path.exists() → .pdf).
    """
    if source.asset and source.asset.file_path:
        fp = source.asset.file_path
        if Path(fp).exists() and fp.lower().endswith(".pdf"):
            return fp
    return None


def _render_section_pages(
    file_path: str, page_start: int, page_end: Optional[int]
) -> List[bytes]:
    """Render physical pages ``page_start..page_end`` (0-based, inclusive) to PNG bytes.

    Uses PyMuPDF (imported lazily inside the helper — matching how
    ``section_commands.py`` imports ``fitz`` — so a missing PyMuPDF can't break
    worker startup / command registration). Page indices are physical; no
    ``page_offset`` is applied here (Decision #8: offset is display-only).
    """
    import fitz  # PyMuPDF — lazy import (matches section_commands.py)

    images: List[bytes] = []
    doc = fitz.open(file_path)
    try:
        n_pages = len(doc)
        start = max(0, page_start)
        end = page_end if page_end is not None else start
        end = min(end, n_pages - 1)
        matrix = fitz.Matrix(_RENDER_ZOOM, _RENDER_ZOOM)
        for idx in range(start, end + 1):
            pix = doc[idx].get_pixmap(matrix=matrix)
            images.append(pix.tobytes("png"))
    finally:
        doc.close()
    return images


def _display_page(physical_idx: int, page_offset: Optional[int]) -> int:
    """Physical 0-based index → printed page label (display only).

    ``page_offset`` = physical index at which printed 'page 1' begins (null =
    identity). Used purely to make the prompt's page reference human-readable.
    """
    return physical_idx - (page_offset or 0) + 1


def _split_cleaned_and_discrepancies(
    text: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Split the model output on a 'DISCREPANCIES:' header.

    Everything before the header is the cleaned text; everything after is the
    discrepancies note. Returns (cleaned, discrepancies) where either may be
    None. A discrepancies body of none/n/a/empty collapses to None.
    """
    if not text:
        return None, None

    match = re.search(r"DISCREPANCIES\s*:", text, re.IGNORECASE)
    if not match:
        return (text.strip() or None), None

    # Trim a leading markdown heading prefix (e.g. "## DISCREPANCIES:") off the
    # cleaned side by cutting at the start of the matched line.
    line_start = text.rfind("\n", 0, match.start()) + 1
    cleaned = text[:line_start].strip()
    discrepancies = text[match.end():].strip()

    if discrepancies.lower().strip(" .") in ("", "none", "n/a", "na", "no discrepancies"):
        discrepancies = None

    return (cleaned or None), discrepancies


def _output_truncation_reason(
    cleaned: Optional[str], content: Optional[str], response
) -> Optional[str]:
    """Why the verify output should be REJECTED as truncated, or None if sane.

    Two failure modes, both observed live (to-fix/004 Finding 2):
      - the reply hit the mandatory ``max_tokens`` cap (Ollama reports
        ``done_reason='length'``; OpenAI-compatible providers use
        ``finish_reason``) — 32/472 sections of a real textbook exceed the
        ~32K-char output budget;
      - the model simply returned far less text than went in, cap or no cap
        (the Preface case: 22,532 chars in, 506 out, no length stop).

    Nothing here writes or raises — the caller records a non-None reason via
    :func:`_record_verify_verdict` and leaves ``cleaned_content`` unset.
    """
    meta = getattr(response, "response_metadata", None) or {}
    stop_reason = str(
        meta.get("done_reason") or meta.get("finish_reason") or ""
    ).lower()
    if stop_reason == "length":
        return (
            "the model stopped at its max_tokens output cap "
            "(stop reason 'length'), so the tail of the section is missing"
        )

    raw_len = len(content or "")
    if cleaned is not None and raw_len:
        kept = len(cleaned) / raw_len
        if kept < _MIN_CLEANED_RATIO:
            return (
                f"the model returned {len(cleaned)} chars for a "
                f"{raw_len}-char section ({kept:.0%} kept, below the "
                f"{_MIN_CLEANED_RATIO:.0%} sanity floor)"
            )
    return None


async def _record_verify_verdict(
    section: SourceSection,
    status: str,
    reason: Optional[str],
    job_id: Optional[str],
) -> None:
    """Persist this section's verify verdict and mirror it to the job's log.

    ``status`` is 'clean' | 'rejected' | 'skipped' (migration 27). The DB field is
    the durable, queryable record — "which chapters are still on the raw parse?"
    is one SELECT. The ``warning`` event is the per-run explanation, and it fires
    only for the non-clean verdicts: a rejected or skipped section leaves the job
    otherwise indistinguishable from a successful one, because neither outcome
    fails it.

    The section save is best-effort-free: it must NOT be swallowed. If we can't
    record that a proof was rejected, the raw parse silently looks proofed, which
    is the exact failure this whole change exists to prevent — so let it raise and
    let the job retry.
    """
    section.verify_status = status
    section.verify_reason = reason
    await section.save()

    if status != "clean" and reason:
        await report_job_warning(job_id, reason)


def _leaf_section_ids(nodes: List[dict]) -> List[str]:
    """Depth-first ids of LEAF sections only (nodes with no children).

    Verify fans out over leaves, not the whole tree: sections nest, so a
    parent's page range covers its children's and proofing every node re-emits
    the document once per tree level — measured 2.6× the book's characters and
    ~2.3 renders per page on a real textbook (to-fix/004 Finding 1). Verify is
    output-bound ("preserve all content"), so that overlap is pure cost. Leaves
    partition the document: full coverage, zero overlap, and far fewer sections
    over the max_tokens output budget (32 → 1 on the same book).
    """
    ids: List[str] = []
    for node in nodes:
        children = node.get("children") or []
        if children:
            ids.extend(_leaf_section_ids(children))
        elif node.get("id"):
            ids.append(str(node["id"]))
    return ids


def _flatten_section_titles(nodes: List[dict]) -> Dict[str, str]:
    """Depth-first flatten of a ``get_sections()`` tree into id → title.

    Used by the per-section fan-outs to stamp job args with the chapter title
    (``label``) and the owning ``source_id``, so the frontend job tray can say
    which chapter a job is about and link the row back to its source.
    """
    titles: Dict[str, str] = {}
    for node in nodes:
        nid = node.get("id")
        if nid:
            titles[str(nid)] = str(node.get("title") or "")
        titles.update(_flatten_section_titles(node.get("children") or []))
    return titles


async def _run_render(
    file_path: str, page_start: int, page_end: Optional[int]
) -> List[bytes]:
    """Run the (sync, CPU-bound) PyMuPDF render off the event loop."""
    import asyncio

    return await asyncio.to_thread(
        _render_section_pages, file_path, page_start, page_end
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@command(
    "verify_clean_section",
    app="open_notebook",
    # Retry hardened 2026-07-05: the original 3×10s-fixed budget structurally
    # lost to heavy-slot model transitions — a chat→vision swap on the gate
    # takes minutes, so every VC job that interleaved with a summary stream
    # 503'd out (observed: 10/10 sample jobs failed this way when mixed;
    # back-to-back VC against a warm model succeeded). Exponential up to 120s
    # over 5 attempts (~4min total) outlasts a swap. Permanent errors (bad id /
    # bad config) still don't retry.
    retry={
        "max_attempts": 5,
        "wait_strategy": "exponential_jitter",
        "wait_min": 10,
        "wait_max": 120,
        "stop_on": [ValueError, ConfigurationError],
    },
)
async def verify_clean_section(
    input_data: VerifyCleanSectionInput,
) -> VerifyCleanSectionOutput:
    """Run the verify pass, then chain the summarize phase if this was the last one.

    The chain lives out here so it fires on EVERY non-raising path — a skipped
    section (no page range, stale generation, oversized span) still has to count
    as "done" or the last skip would strand the summarize phase forever.

    A job that raises is left to retry, and stays `running` in the meantime, so a
    concurrent sibling won't mistake itself for the last. The one case the chain
    can't cover is a section whose final retry fails terminally — nothing is left
    to observe it. That's what the manual re-run endpoint is for.
    """
    out = await _verify_clean_section_impl(input_data)
    await _chain_summarize_if_last(input_data)
    return out


async def _chain_summarize_if_last(input_data: VerifyCleanSectionInput) -> None:
    """Start the summarize phase once no verify job for this source is pending.

    Phases are SEQUENCED, not concurrent, for two reasons. (1) verify uses the
    vision model and summarize uses the transformation model; both are heavy
    Ollama, and the single heavy slot holds one at a time, so interleaving them
    forces a 35B evict+load between jobs. (2) summarize_section prefers
    `cleaned_content` — verify's output — so running it first means summaries are
    built from unproofed text.
    """
    source_id = input_data.source_id
    job_id = _job_id(input_data)
    if not source_id or not job_id:
        return  # untracked / unstamped job (tests, manual single-section run)
    if await siblings_in_flight(source_id, "verify_clean_section", job_id):
        return
    logger.info(
        f"verify_clean_section: last verify job for {source_id} finished; "
        f"starting the summarize phase"
    )
    await submit_command_once(
        "open_notebook", "summarize_source", {"source_id": source_id}, source_id
    )


async def _verify_clean_section_impl(
    input_data: VerifyCleanSectionInput,
) -> VerifyCleanSectionOutput:
    """Vision verify-clean a single ``source_section``.

    Renders the section's physical pages, sends them + the parsed ``content`` to
    the vision model, and writes the corrected text to ``cleaned_content``.
    NEVER touches ``section.content`` or ``Source.full_text`` (immutable raw).
    The verdict lands on ``verify_status``/``verify_reason``; the model's freeform
    discrepancy narration is logged and dropped (see the module docstring).

    Skips gracefully (cleaned_content=None, no crash) when: no PDF file, not a
    PDF, no page range, section too large, vision model unconfigured, or an
    empty model response.
    """
    job_id = _job_id(input_data)
    await report_job_progress(job_id, "Loading section")

    # A missing section is OBSOLETE WORK, not an error. build_sections is
    # delete-then-rebuild, so any rebuild that lands while this job sits in the
    # queue mints new section ids and orphans this one. Raising here marked the
    # job failed AND burned 5 retries per orphan (observed: 89 failed + 377
    # queued orphans on one book, saturating the worker). Skip quietly instead.
    try:
        section = await SourceSection.get(input_data.source_section_id)
    except NotFoundError:
        if not await section_is_gone(input_data.source_section_id):
            raise  # live DB problem, not a deleted row — let the job retry
        logger.info(
            f"verify_clean_section: section {input_data.source_section_id} no "
            f"longer exists (superseded by a section rebuild); skipping"
        )
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=None)

    source = await Source.get(str(section.source))
    if not source:
        raise ValueError(f"Source '{section.source}' not found")

    # Same staleness, caught one step earlier: the section id still resolves but
    # the source has been re-parsed since fan-out, so this tree is on its way
    # out. Only enforce when the job carried a stamp (see the input model).
    if (
        input_data.parse_generation is not None
        and source.parse_generation != input_data.parse_generation
    ):
        logger.info(
            f"verify_clean_section: section {section.id} was queued for parse "
            f"generation {input_data.parse_generation} but source is now at "
            f"{source.parse_generation}; skipping obsolete verify"
        )
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=None)

    # --- Resolve the source PDF ---
    file_path = _resolve_pdf_path(source)
    if not file_path:
        logger.info(
            f"verify_clean_section: section {section.id} — no on-disk PDF "
            f"(asset={source.asset}); skipping"
        )
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=None)

    if section.page_start is None:
        logger.info(
            f"verify_clean_section: section {section.id} has no page range; skipping"
        )
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=None)

    # --- Guard pathological page spans (skip-and-record, never truncate) ---
    span = (section.page_end or section.page_start) - section.page_start + 1
    if span > _MAX_VERIFY_PAGES:
        note = (
            f"Section '{section.title}' spans {span} pages "
            f"(> {_MAX_VERIFY_PAGES}) — too large for a single-pass vision "
            f"verify; skipped. Re-chapter into smaller sections to clean it."
        )
        logger.warning(f"verify_clean_section: {note}")
        await _record_verify_verdict(section, "skipped", note, job_id)
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=note)

    # --- Render pages to PNG ground-truth images ---
    await report_job_progress(job_id, "Rendering pages")
    try:
        page_images = await _run_render(
            file_path, section.page_start, section.page_end
        )
    except Exception as exc:
        # Render failure is likely transient-ish (locked file / bad page) — let it
        # propagate so this one section's job retries; other sections are isolated.
        logger.error(
            f"verify_clean_section: failed to render pages for section "
            f"{section.id}: {exc}"
        )
        raise

    if not page_images:
        logger.info(
            f"verify_clean_section: section {section.id} rendered 0 pages; skipping"
        )
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=None)

    # --- Build the vision HumanMessage (pages + parsed text + instruction) ---
    disp_start = _display_page(section.page_start, source.page_offset)
    disp_end = _display_page(
        section.page_end or section.page_start, source.page_offset
    )
    text_prompt = (
        f"Below are the rendered page images (pp. {disp_start}-{disp_end}) of a "
        f'document section titled "{section.title}", followed by the '
        f"machine-parsed text of that same section. The parsed text may contain "
        f"artifacts from automatic extraction.\n\n"
        f"{_VERIFY_INSTRUCTION}\n\n"
        f"Output ONLY the corrected text of the section.\n\n"
        f"--- PARSED TEXT ---\n{section.content or ''}"
    )
    message = await provision_vision_message(page_images, text_prompt)

    # --- Provision the vision model (Decision #6) ---
    # NOTE: we deliberately use get_vision_model() directly (not
    # provision_langchain_model) so a large section can never be silently routed
    # to the non-vision large_context_model, and so an unconfigured slot returns
    # None instead of raising. max_tokens=8192 is MANDATORY (B1 pilot: unset ->
    # silent empty output on this thinking model).
    try:
        vision_model = await model_manager.get_vision_model(
            max_tokens=8192, num_ctx=_VERIFY_NUM_CTX
        )
    except ConfigurationError as exc:
        note = f"Vision model misconfigured — verify-clean skipped: {exc}"
        logger.warning(f"verify_clean_section: {note}")
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=note)

    if vision_model is None:
        note = (
            "No default_vision_model configured — verify-clean skipped "
            "(configure Settings -> Models -> Vision)."
        )
        logger.warning(f"verify_clean_section: section {section.id}: {note}")
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=note)

    # --- Invoke ---
    # Reasoning OFF: verify is verbatim reproduction — thinking adds nothing,
    # and this model intermittently reasons through the ENTIRE 8192-token
    # output budget without ever starting the answer (observed live:
    # eval_count == max_tokens, done_reason 'length', empty content, ~3.5 min
    # of GPU per no-op job).
    lc_model = apply_reasoning_flag(vision_model.to_langchain(), False)

    # The gate admits ONE heavy generation at a time and refuses the rest with a
    # 503 after a 30s lock timeout. A 35B vision pass over page images runs for
    # minutes, so concurrent verify jobs used to 503 each other out and exhaust
    # their retry budget (the hardened retry below could never outlast a lock it
    # was itself contending for). Serialize in-process instead: only one job
    # reaches the gate, the rest wait here.
    defaults = await model_manager.get_defaults()
    lane = await heavy_lane_for(defaults.default_vision_model)
    if lane is heavy_lane and heavy_lane.locked():
        await report_job_progress(job_id, "Waiting for the local model")

    try:
        async with lane:
            await report_job_progress(job_id, "Running vision verify")
            response = await lc_model.ainvoke([message])
    except Exception as e:
        # BLOCKED, not BROKEN: the heavy slot was busy (gate 503 / rate limit),
        # typically because the slot is mid-swap to another 35B model. Requeue
        # rather than burn a retry attempt and eventually surface as `failed`.
        if is_resource_busy(e) and input_data.requeue_count < MAX_REQUEUES:
            await report_job_progress(job_id, "Waiting for the local model")
            await requeue_job(
                "open_notebook",
                "verify_clean_section",
                {
                    "source_section_id": input_data.source_section_id,
                    "source_id": input_data.source_id,
                    "parse_generation": input_data.parse_generation,
                    "requeue_count": input_data.requeue_count + 1,
                },
            )
            logger.info(
                f"verify_clean_section: section {section.id} requeued "
                f"(heavy slot busy, attempt {input_data.requeue_count + 1})"
            )
            return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=None)

        # Classify raw provider errors into typed, user-friendly exceptions.
        # Transient classes still retry (5× exp-jitter above); ConfigurationError
        # stays permanent via stop_on.
        exc_class, err_message = classify_error(e)
        raise exc_class(f"Vision verify failed: {err_message}") from e
    pre_clean = extract_text_content(response.content)
    raw = clean_thinking_content(pre_clean)

    if not raw or not raw.strip():
        # Diagnose, don't just skip: "empty" can be a genuinely empty reply, a
        # reply that was 100% thinking (token cap hit mid-think shows up as a
        # 'length' stop with an unterminated <think> block), or a provider that
        # moved the answer out of `content`. Log enough to tell which.
        meta = getattr(response, "response_metadata", None) or {}
        extras = getattr(response, "additional_kwargs", None) or {}
        note = (
            f"Section '{section.title}' verify output rejected: the vision model "
            f"returned empty content (it can spend its entire output budget on the "
            f"thinking prelude — to-fix/004 Finding 4). cleaned_content left unset "
            f"(raw parse preserved). Re-run verify-clean to retry."
        )
        logger.warning(
            f"verify_clean_section: section {section.id}: {note} "
            f"[pre-clean len={len(pre_clean)}, "
            f"pre-clean head={pre_clean[:200]!r}, "
            f"response_metadata={meta!r}, "
            f"additional_kwargs keys={list(extras.keys())!r}]"
        )
        # Same class of failure as a truncated proof: the model produced nothing
        # usable and the section stays on the raw parse. Without a verdict it would
        # be indistinguishable from a section verify never reached — which is how 8
        # sections of the test book went unaccounted for.
        await _record_verify_verdict(section, "rejected", note, job_id)
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=note)

    cleaned, discrepancies = _split_cleaned_and_discrepancies(raw)

    # --- Output-sanity guard: never persist a truncated proof ---
    # A short reply used to be written straight to cleaned_content, and every
    # reader (chat context, summaries, agent tools) prefers that layer — so a
    # truncation silently shortened the chapter everywhere. Reject instead:
    # flag it, keep the raw parse authoritative.
    truncation = _output_truncation_reason(cleaned, section.content, response)
    if truncation:
        note = (
            f"Section '{section.title}' verify output rejected: {truncation}. "
            f"cleaned_content left unset (raw parse preserved). Split the "
            f"section into smaller ones or re-run verify-clean to retry."
        )
        logger.warning(f"verify_clean_section: section {section.id}: {note}")
        await _record_verify_verdict(section, "rejected", note, job_id)
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=note)

    # --- Persist: cleaned layer only; raw is immutable ---
    await report_job_progress(job_id, "Saving cleaned content")
    if cleaned:
        section.cleaned_content = cleaned
        logger.info(
            f"verify_clean_section: wrote cleaned_content ({len(cleaned)} chars) "
            f"for section {section.id}"
        )
    # One save for both the cleaned layer and the verdict. 'clean' is recorded even
    # when the model returned no cleaned text (a no-op proof of an already-correct
    # section): the point of the field is to distinguish "verify ran and was happy"
    # from "verify never reached this section" (NONE).
    await _record_verify_verdict(section, "clean", None, job_id)

    if discrepancies:
        # The model's freeform narration about what it saw. It is NOT a verdict —
        # the proof was accepted, and this text is the model thinking out loud
        # about a comparison that already returned an answer. It used to become a
        # verify_flag insight, i.e. ~107K chars across this book that rode into
        # every chat turn and into vector search. Log it and drop it.
        logger.info(
            f"verify_clean_section: section {section.id} discrepancy note "
            f"({len(discrepancies)} chars): {discrepancies}"
        )

    return VerifyCleanSectionOutput(
        cleaned_content=cleaned, discrepancies=discrepancies
    )


@command(
    "verify_clean_source",
    app="open_notebook",
    # Retries cover the eventual-consistency race with build_sections: when the
    # ingest graph fires this immediately after submit_sections the section tree
    # may be empty OR (worse) mid-rebuild and partial — we raise-to-retry until
    # the build_sections job for this source reaches a terminal state AND the
    # tree is non-empty. Window sized for multi-minute chaptering on real books
    # (observed: 54s for a 472-section textbook). Permanent errors (bad id)
    # stop immediately.
    retry={
        "max_attempts": 8,
        "wait_strategy": "exponential_jitter",
        "wait_min": 10,
        "wait_max": 120,
        "stop_on": [ValueError, ConfigurationError],
    },
)
async def verify_clean_source(
    input_data: VerifyCleanSourceInput,
) -> VerifyCleanSourceOutput:
    """Fan out one ``verify_clean_section`` job per LEAF section of a source.

    Leaves only — parents' page ranges duplicate their children's, and verify
    re-emits every character it is shown (see ``_leaf_section_ids``). Callable
    both fire-and-forget from the ingest graph (after chaptering) and as a
    manual re-run path. Per-section submit is wrapped so one failure can't
    poison the others. If no sections exist yet (build_sections still in flight)
    we raise so the job retries — a qualifying PDF always yields >= 1 section.
    """
    start_time = time.time()
    job_id = _job_id(input_data)
    await report_job_progress(job_id, "Checking chaptering status")

    source = await Source.get(input_data.source_id)
    if not source:
        raise ValueError(f"Source '{input_data.source_id}' not found")

    if await blocks_in_flight(input_data.source_id):
        # Defer, don't retry: build_blocks can run for minutes and will resubmit
        # us once it has rebuilt the tree. Retrying here would exhaust the budget
        # and surface a red job for what is a normal ordering wait.
        note = (
            f"Deferred: block parse (build_blocks) still in flight for source "
            f"{input_data.source_id}; it will resubmit verify_clean_source once "
            f"the final section tree exists."
        )
        logger.info(f"verify_clean_source: {note}")
        return VerifyCleanSourceOutput(
            success=True,
            source_id=input_data.source_id,
            jobs_submitted=0,
            error_message=note,
        )

    if await chaptering_in_flight(input_data.source_id):
        # build_sections deletes + rebuilds the tree; sampling it now would fan
        # out over a partial tree (observed: 117/472). Raise so surreal_commands
        # retries with backoff until chaptering reaches a terminal state.
        raise RuntimeError(
            f"Chaptering (build_sections) still in flight for source "
            f"{input_data.source_id} — section tree incomplete; will retry"
        )

    tree = await source.get_sections()
    # Leaf sections only — see _leaf_section_ids. Every non-empty tree has
    # leaves, so the empty check below still means "chaptering hasn't landed".
    section_ids = _leaf_section_ids(tree)

    if not section_ids:
        # Eventual-consistency: chaptering (build_sections) may not have landed
        # yet. Raise so surreal_commands retries with backoff.
        raise RuntimeError(
            f"No sections yet for source {input_data.source_id} — "
            f"chaptering may still be running; will retry"
        )

    # --- Pre-flight: is a vision model configured at all? ---
    # Without this, N per-section jobs each "complete" as silent no-ops (the
    # skip note lives only in each job's result payload) — observed live as
    # 117 completed jobs, 0 cleaned_content, 0 insights, nothing visible in the
    # UI. Skip the fan-out entirely and leave ONE visible warning on this job.
    #
    # "Unconfigured" and "configured but unresolvable" are NOT the same. Model.get
    # funnels every exception into NotFoundError (open_notebook/domain/base.py),
    # so a transient DB timeout used to surface here as "no vision model
    # configured" and skip the entire document — observed live: a 'timed out
    # during opening handshake' under queue load silently skipped a 472-section
    # book and left a misleading skip warning. Only an unset default is a real
    # skip; a resolution failure raises so the job retries.
    defaults = await model_manager.get_defaults()
    if defaults.default_vision_model:
        try:
            vision_model = await model_manager.get_vision_model()
        except Exception as exc:
            raise RuntimeError(
                f"Vision model {defaults.default_vision_model} is configured but "
                f"could not be resolved ({exc}); will retry rather than skip "
                f"verify-clean for source {input_data.source_id}"
            ) from exc
        if vision_model is None:
            raise RuntimeError(
                f"Vision model {defaults.default_vision_model} resolved to None "
                f"for source {input_data.source_id}; will retry"
            )
    else:
        vision_model = None

    if vision_model is None:
        note = (
            "Verify-clean skipped for this document: no default vision model "
            "is configured (Settings -> Models -> Vision). Re-run verify-clean "
            "after configuring one."
        )
        logger.warning(
            f"verify_clean_source: source {input_data.source_id}: {note}"
        )
        # Document-level, so there is no section to hang a verdict on. The fan-out
        # job's own event log is the only place this can live — and it's the right
        # one: this job is what the user opens in /activity when the book never
        # got proofed.
        await report_job_warning(job_id, note)
        # No verify jobs will exist, so nothing will chain the next phase — start
        # it here. Summaries fall back to raw `content` when there's no
        # `cleaned_content`, so the document still gets summarized.
        await submit_command_once(
            "open_notebook",
            "summarize_source",
            {"source_id": input_data.source_id},
            input_data.source_id,
        )
        return VerifyCleanSourceOutput(
            success=False,
            source_id=input_data.source_id,
            sections_found=len(section_ids),
            jobs_submitted=0,
            error_message=note,
        )

    await report_job_progress(
        job_id, "Submitting section verify jobs", sections=len(section_ids)
    )
    jobs_submitted = 0
    section_titles = _flatten_section_titles(tree)
    for section_id in section_ids:
        try:
            cmd_id = submit_command(
                "open_notebook",
                "verify_clean_section",
                {
                    "source_section_id": section_id,
                    # Staleness stamp: if the source is re-parsed before this job
                    # runs, its section id is dead and the job self-skips.
                    "parse_generation": source.parse_generation,
                    # Job-tray metadata (ignored by the Pydantic input model):
                    # label → row title, source_id → click-to-origin route.
                    "source_id": input_data.source_id,
                    "label": section_titles.get(section_id, ""),
                },
            )
            logger.info(
                f"verify_clean_source: submitted verify_clean_section for "
                f"{section_id}: {cmd_id}"
            )
            jobs_submitted += 1
        except Exception as exc:
            # Isolation: one section's submit failure must not stop the rest.
            logger.warning(
                f"verify_clean_source: failed to submit verify_clean_section "
                f"for {section_id}: {exc}"
            )

    processing_time = time.time() - start_time
    logger.info(
        f"verify_clean_source: {len(section_ids)} sections, "
        f"{jobs_submitted} jobs submitted for {input_data.source_id} "
        f"in {processing_time:.2f}s"
    )
    return VerifyCleanSourceOutput(
        success=True,
        source_id=input_data.source_id,
        sections_found=len(section_ids),
        jobs_submitted=jobs_submitted,
    )
