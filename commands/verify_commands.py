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
    job per section of a source. Wrapped per-section so one section's submit
    failure can't poison the rest.

Design notes:
  - Decision #6: uses the configured ``default_vision_model`` (deployed Ollama
    Qwen). If unconfigured / misconfigured we skip gracefully (cleaned_content
    left None) rather than crashing — the text-only fallback is a follow-up.
  - Decision #8: page indices are physical (0-based) everywhere; ``page_offset``
    is applied ONLY to compute display page labels in the prompt, never for
    slicing.
  - B1 pilot: this thinking-capable vision model silently returns empty content
    when ``max_tokens`` is unset — we pass ``max_tokens=8192`` explicitly
    (mandatory). Low-confidence output is routed to a ``verify_flag`` insight
    rather than blind-overwriting anything.
"""
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command, submit_command

from open_notebook.ai.models import model_manager
from open_notebook.ai.vision_utils import provision_vision_message
from open_notebook.database.repository import repo_query
from open_notebook.domain.notebook import Source, SourceSection
from open_notebook.exceptions import ConfigurationError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content

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
# verify_flag rather than truncating (truncation would silently drop content).
# Real chapters are comfortably under this bound.
_MAX_VERIFY_PAGES = 50

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


def _flatten_section_ids(nodes: List[dict]) -> List[str]:
    """Depth-first flatten of a ``get_sections()`` tree into a list of ids."""
    ids: List[str] = []
    for node in nodes:
        nid = node.get("id")
        if nid:
            ids.append(str(nid))
        children = node.get("children") or []
        ids.extend(_flatten_section_ids(children))
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


async def _chaptering_in_flight(source_id: str) -> bool:
    """True while a ``build_sections`` job for this source is queued or running.

    ``build_sections`` is delete-then-rebuild (idempotent), so any fan-out that
    samples the section tree mid-build sees a PARTIAL tree, not an empty one —
    observed live on the Hands-on-ML book: ``verify_clean_source`` ran 6s into
    a 54s rebuild and fanned out over 117 of the eventual 472 sections. An
    empty-tree check alone therefore cannot close the race; orchestrators must
    also wait for chaptering to reach a terminal state. Command rows carry no
    timestamps, so "any non-terminal build_sections row for this source" is the
    whole predicate. Shared by ``verify_clean_source`` and
    ``summarize_source`` (commands/summary_commands.py).
    """
    rows = await repo_query(
        "SELECT count() AS n FROM command "
        "WHERE name = 'build_sections' AND args.source_id = $sid "
        "AND status IN ['new', 'running'] GROUP ALL",
        {"sid": source_id},
    )
    return bool(rows and rows[0].get("n", 0) > 0)


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
    """Vision verify-clean a single ``source_section``.

    Renders the section's physical pages, sends them + the parsed ``content`` to
    the vision model, and writes the corrected text to ``cleaned_content``.
    NEVER touches ``section.content`` or ``Source.full_text`` (immutable raw).
    Any flagged discrepancies are stored as a ``verify_flag`` SourceInsight.

    Skips gracefully (cleaned_content=None, no crash) when: no PDF file, not a
    PDF, no page range, section too large, vision model unconfigured, or an
    empty model response.
    """
    section = await SourceSection.get(input_data.source_section_id)
    if not section:
        raise ValueError(
            f"SourceSection '{input_data.source_section_id}' not found"
        )

    source = await Source.get(str(section.source))
    if not source:
        raise ValueError(f"Source '{section.source}' not found")

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

    # --- Guard pathological page spans (skip-with-flag, never truncate) ---
    span = (section.page_end or section.page_start) - section.page_start + 1
    if span > _MAX_VERIFY_PAGES:
        note = (
            f"Section '{section.title}' spans {span} pages "
            f"(> {_MAX_VERIFY_PAGES}) — too large for a single-pass vision "
            f"verify; skipped. Re-chapter into smaller sections to clean it."
        )
        logger.warning(f"verify_clean_section: {note}")
        await source.add_insight("verify_flag", note)
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=note)

    # --- Render pages to PNG ground-truth images ---
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
        vision_model = await model_manager.get_vision_model(max_tokens=8192)
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
    lc_model = vision_model.to_langchain()
    try:
        response = await lc_model.ainvoke([message])
    except Exception as e:
        # Classify raw provider errors into typed, user-friendly exceptions.
        # Transient classes still retry (5× exp-jitter above); ConfigurationError
        # stays permanent via stop_on.
        exc_class, err_message = classify_error(e)
        raise exc_class(f"Vision verify failed: {err_message}") from e
    raw = clean_thinking_content(extract_text_content(response.content))

    if not raw or not raw.strip():
        note = (
            "Vision model returned empty content — cleaned_content left unset "
            "(raw parse preserved)."
        )
        logger.warning(f"verify_clean_section: section {section.id}: {note}")
        return VerifyCleanSectionOutput(cleaned_content=None, discrepancies=note)

    cleaned, discrepancies = _split_cleaned_and_discrepancies(raw)

    # --- Persist: cleaned layer only; raw is immutable ---
    if cleaned:
        section.cleaned_content = cleaned
        await section.save()
        logger.info(
            f"verify_clean_section: wrote cleaned_content ({len(cleaned)} chars) "
            f"for section {section.id}"
        )

    if discrepancies:
        # Low-confidence / unreconcilable items → verify_flag insight, never a
        # blind overwrite of the raw text.
        await source.add_insight("verify_flag", discrepancies)
        logger.info(
            f"verify_clean_section: recorded verify_flag for section {section.id}"
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
    """Fan out one ``verify_clean_section`` job per section of a source.

    Callable both fire-and-forget from the ingest graph (after chaptering) and
    as a manual re-run path. Per-section submit is wrapped so one failure can't
    poison the others. If no sections exist yet (build_sections still in flight)
    we raise so the job retries — a qualifying PDF always yields >= 1 section.
    """
    start_time = time.time()

    source = await Source.get(input_data.source_id)
    if not source:
        raise ValueError(f"Source '{input_data.source_id}' not found")

    if await _chaptering_in_flight(input_data.source_id):
        # build_sections deletes + rebuilds the tree; sampling it now would fan
        # out over a partial tree (observed: 117/472). Raise so surreal_commands
        # retries with backoff until chaptering reaches a terminal state.
        raise RuntimeError(
            f"Chaptering (build_sections) still in flight for source "
            f"{input_data.source_id} — section tree incomplete; will retry"
        )

    tree = await source.get_sections()
    section_ids = _flatten_section_ids(tree)

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
    # UI. Skip the fan-out entirely and leave ONE visible verify_flag insight.
    try:
        vision_model = await model_manager.get_vision_model()
    except ConfigurationError as exc:
        vision_model = None
        logger.warning(f"verify_clean_source: vision model misconfigured: {exc}")
    if vision_model is None:
        note = (
            "Verify-clean skipped for this document: no default vision model "
            "is configured (Settings -> Models -> Vision). Re-run verify-clean "
            "after configuring one."
        )
        logger.warning(
            f"verify_clean_source: source {input_data.source_id}: {note}"
        )
        await source.add_insight("verify_flag", note)
        return VerifyCleanSourceOutput(
            success=False,
            source_id=input_data.source_id,
            sections_found=len(section_ids),
            jobs_submitted=0,
            error_message=note,
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
