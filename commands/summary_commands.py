"""
Per-section summaries + document abstract for Open Notebook (Track B, Chunk B3).

Three commands, layered on top of A3's section tree and B2's verify-clean layer:
  - ``summarize_source``         : fan-out orchestrator — waits (raise-to-retry)
    for chaptering to reach a terminal state, then submits one
    ``summarize_section`` job per section. Mirrors ``verify_clean_source``.
  - ``summarize_section``        : summarize one ``source_section`` concisely.
    Prefers ``cleaned_content`` (B2's vision-verified layer), falling back to the
    raw parsed ``content`` when verify-clean was skipped. Verify and summarize
    are SEQUENCED phases: the last ``verify_clean_section`` to finish submits
    ``summarize_source`` (``verify_commands._chain_summarize_if_last``). They ran
    concurrently until 2026-07-09, which both starved summaries of the proofed
    text and thrashed the single local heavy slot between two 35B Ollama models
    (vision ↔ transformation) on every job swap. The job that writes the LAST
    missing summary submits ``generate_source_abstract`` (event-driven trigger).
  - ``generate_source_abstract`` : roll up every section summary into one
    document-level abstract, stored as a ``SourceInsight`` (idempotent —
    replaces any prior ``abstract`` insight rather than duplicating).

Design notes:
  - Coordinator Decision #4 (derived layers) / #7 (tiered chat context): these
    are the "chapter-summary outline" + "doc abstract" layers the chat agent
    and TOC sidebar consume instead of the raw ``full_text`` blob.
  - On the ingest path, ``generate_source_abstract`` is submitted by the
    event-driven trigger in ``summarize_section`` (last missing summary), so
    its readiness gate passes on the first or second attempt. On the manual
    re-run path (``Source.summarize_sections()``) it is still submitted
    upfront, where existing summaries let the gate pass immediately. Either
    way it raises to retry (with backoff) until every section that actually
    has text has a summary — mirroring the eventual-consistency pattern
    ``verify_clean_source`` uses for ``build_sections``
    (see ``commands/verify_commands.py``). It reads
    ``Source.get_sections()`` (not the lighter ``get_outline()``) so it can
    tell text-bearing sections apart from structural/heading-only nodes
    (e.g. a "Part I" divider immediately followed by a subheading) — those
    never get a summary by design (``summarize_section`` skips empty text),
    so requiring 100% of *outline* nodes to have a summary would deadlock.
"""
import time
from typing import Dict, List, Optional

from langchain_core.messages import HumanMessage
from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command, submit_command

from commands._heavy_lane import heavy_lane, heavy_lane_for

# Shared race-guard + tree-flatten helpers live with the B2 orchestrator; both
# fan-outs must gate on the same "chaptering reached a terminal state" predicate.
from commands._job_guards import (
    MAX_REQUEUES,
    blocks_in_flight,
    chaptering_in_flight,
    is_resource_busy,
    requeue_job,
    section_is_gone,
)
from commands.verify_commands import _flatten_section_titles
from open_notebook.ai.models import model_manager
from open_notebook.ai.provision import (
    apply_reasoning_flag,
    provision_langchain_model,
)
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Source, SourceSection
from open_notebook.exceptions import ConfigurationError, NotFoundError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.job_progress import report_job_progress
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
# Pydantic I/O models
# ---------------------------------------------------------------------------


class SummarizeSectionInput(CommandInput):
    source_section_id: str
    # Declared (not just passed) so it PERSISTS into the command row's args —
    # undeclared keys are dropped, which is why cancel_source_jobs could never
    # see per-section jobs.
    source_id: Optional[str] = None
    # Stamped by summarize_source at fan-out time from source.parse_generation.
    # A newer generation means the section tree has been rebuilt since and this
    # id belongs to a dead generation. None = unstamped (manual re-run) → run.
    parse_generation: Optional[int] = None
    # Incremented each time the job is requeued for a busy heavy slot.
    requeue_count: int = 0


class SummarizeSectionOutput(CommandOutput):
    summary: Optional[str] = None


class SummarizeSourceInput(CommandInput):
    source_id: str


class SummarizeSourceOutput(CommandOutput):
    success: bool
    source_id: str
    sections_found: int = 0
    jobs_submitted: int = 0
    error_message: Optional[str] = None


class GenerateSourceAbstractInput(CommandInput):
    source_id: str


class GenerateSourceAbstractOutput(CommandOutput):
    success: bool
    source_id: str
    abstract: Optional[str] = None
    error_message: Optional[str] = None


# Context window for the local transformation model. Esperanto's ChatOllama
# wrapper defaults num_ctx to 8192 — real chapters (level-1 median ~72K chars
# ≈ 18K tokens) silently overflowed it and Ollama truncated the input.
_SUMMARY_NUM_CTX = 32768

# to-fix/003 defense-in-depth: hard cap on summarizer input, sized to actually
# fit _SUMMARY_NUM_CTX: ~120K chars ≈ 30K tokens, leaving room for the prompt
# and the (small) reply. Anything longer is explicitly truncated with a logged
# warning — for a routing blurb the opening of the section carries the signal.
_MAX_SUMMARY_INPUT_CHARS = 120_000

# Tiered-summary policy (2026-07-05): summaries exist for ROUTING — they earn
# their keep where reading the real text is expensive (level 1 chapters avg
# ~65K chars ≈ 16 get_section calls; level 2 sections avg ~9.5K). At level 3+
# the section itself fits in a single get_section call, so a dense summary
# costs nearly as much context as the real text while adding outline bloat.
# Fan-out, the abstract readiness gate, and the abstract roll-up all use this
# bound. summarize_section itself stays level-agnostic (explicit per-section
# requests still work).
_MAX_SUMMARY_LEVEL = 2

# Size bound (to-fix/004 Finding 3): depth is a bad proxy for size — 17% of one
# book's level-≤2 sections were under 2,000 chars. A section that small costs
# ~500 tokens to just read, so summarizing it to a 300-char routing blurb saves
# nothing while spending a full serialized 35B generation: the section IS its
# own summary. Applied by the fan-out, the stamped per-section job, and BOTH
# abstract readiness gates (`_remaining_unsummarized` and the pending check in
# `generate_source_abstract`) — if any gate expected a summary the others never
# produce, the abstract would retry to exhaustion and fail.
_MIN_SUMMARY_CHARS = 2000

# Consumers show at most 300 chars of a summary (get_outline summary_chars=300
# in chat_tools / claude_agent_tools) — summaries exist purely to route the
# agent to the right get_section call. Prompting for an unbounded "concise"
# summary generated prose at a 998-char median (12K max), ~80% of it truncated
# away on every read (to-fix/004 Finding 3). The prompt bounds the answer.
_SUMMARY_INSTRUCTION = (
    "Write a 1-2 sentence summary (300 characters at most) of the document "
    "section below. It is a routing blurb in a table of contents, read only to "
    "decide whether to open the section — state what the section covers, not "
    "the details. Output only the summary."
)


def _section_text_len(node: Dict) -> int:
    """Effective text length of a tree node — cleaned layer when present, else
    the raw parse; the same preference order ``summarize_section`` reads."""
    text = node.get("cleaned_content") or node.get("content") or ""
    return len(text.strip())


def _summary_target_ids(nodes: List[Dict]) -> List[str]:
    """Depth-first ids of nodes at level ≤ ``_MAX_SUMMARY_LEVEL`` with at
    least ``_MIN_SUMMARY_CHARS`` of text (smaller sections are their own
    summary — see the bound's comment)."""
    ids: List[str] = []
    for node in nodes:
        nid = node.get("id")
        if (
            nid
            and (node.get("level") or 1) <= _MAX_SUMMARY_LEVEL
            and _section_text_len(node) >= _MIN_SUMMARY_CHARS
        ):
            ids.append(str(nid))
        ids.extend(_summary_target_ids(node.get("children") or []))
    return ids


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _flatten_sections_for_abstract(nodes: List[Dict]) -> List[Dict]:
    """Depth-first flatten of a ``get_sections()`` tree into ordered rows.

    Each row carries ``title``, ``summary``, and ``text_len`` (effective text
    size — ``cleaned_content`` or ``content``). Used both to build the roll-up
    prompt and to gate readiness without deadlocking on nodes that never
    receive a summary by design: structural (heading-only) parents and
    sections under ``_MIN_SUMMARY_CHARS``.
    """
    flat: List[Dict] = []
    for node in nodes:
        flat.append(
            {
                "title": node.get("title") or "(untitled)",
                "level": node.get("level") or 1,
                "summary": node.get("summary"),
                "text_len": _section_text_len(node),
            }
        )
        flat.extend(_flatten_sections_for_abstract(node.get("children") or []))
    return flat


async def _remaining_unsummarized(source_id: str) -> int:
    """Count sections of a source that still need (and lack) a summary.

    Mirrors ``generate_source_abstract``'s readiness gate: a section needs a
    summary only when it is at level ≤ ``_MAX_SUMMARY_LEVEL`` AND its effective
    text (``cleaned_content`` when non-blank, else ``content``) reaches
    ``_MIN_SUMMARY_CHARS`` — heading-only nodes and sub-threshold sections
    never get one by design. Used by the event-driven abstract trigger in
    ``summarize_section``.

    The cleaned-else-raw preference is computed here in Python (SurrealQL's
    ``??`` only handles NONE, not blank strings, and inline IF expressions are
    dialect-sensitive); the query ships lengths, not content.
    """
    rows = await repo_query(
        """
        SELECT
            string::len(string::trim(cleaned_content ?? '')) AS clean_len,
            string::len(string::trim(content ?? '')) AS raw_len,
            string::len(string::trim(summary ?? '')) AS summary_len
        FROM source_section
        WHERE source = $src AND level <= $max_level
        """,
        {"src": ensure_record_id(source_id), "max_level": _MAX_SUMMARY_LEVEL},
    )
    remaining = 0
    for row in rows or []:
        clean_len = int(row.get("clean_len") or 0)
        text_len = clean_len if clean_len > 0 else int(row.get("raw_len") or 0)
        if text_len >= _MIN_SUMMARY_CHARS and int(row.get("summary_len") or 0) == 0:
            remaining += 1
    return remaining


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@command(
    "summarize_section",
    app="open_notebook",
    # Plan spec intent: max_retries=2 (=> 3 attempts incl. initial), delay=5s.
    # Translated to the installed surreal_commands RetryConfig schema (see
    # coordinator Decision #15 / B2's commands/verify_commands.py) — there is
    # no max_retries / delay_seconds field on the real RetryConfig.
    retry={
        "max_attempts": 3,
        "wait_strategy": "fixed",
        "wait_time": 5,
        "stop_on": [ValueError, ConfigurationError],
    },
)
async def summarize_section(
    input_data: SummarizeSectionInput,
) -> SummarizeSectionOutput:
    """Summarize a single ``source_section`` concisely.

    Prefers ``cleaned_content``; falls back to raw ``content`` when
    verify-clean (B2) hasn't landed yet. Skips gracefully (summary=None, no
    crash) when the section has no text or the model returns empty output.
    """
    job_id = _job_id(input_data)
    await report_job_progress(job_id, "Loading section")

    # A missing section is OBSOLETE WORK, not an error — build_sections is
    # delete-then-rebuild, so a rebuild landing while this job sits in the queue
    # orphans its section id. Raising marked the job failed and burned retries
    # per orphan (the same storm that hit verify_clean_section). Skip quietly.
    try:
        section = await SourceSection.get(input_data.source_section_id)
    except NotFoundError:
        if not await section_is_gone(input_data.source_section_id):
            raise  # live DB problem, not a deleted row — let the job retry
        logger.info(
            f"summarize_section: section {input_data.source_section_id} no "
            f"longer exists (superseded by a section rebuild); skipping"
        )
        return SummarizeSectionOutput(summary=None)

    # Same staleness, caught one step earlier: the id resolves but the source has
    # been re-parsed since fan-out. Only enforced when the job carried a stamp.
    if input_data.parse_generation is not None:
        source = await Source.get(str(section.source))
        if source and source.parse_generation != input_data.parse_generation:
            logger.info(
                f"summarize_section: section {section.id} was queued for parse "
                f"generation {input_data.parse_generation} but source is now at "
                f"{source.parse_generation}; skipping obsolete summary"
            )
            return SummarizeSectionOutput(summary=None)

    text = section.cleaned_content or section.content
    if not text or not text.strip():
        logger.info(
            f"summarize_section: section {section.id} has no text; skipping"
        )
        return SummarizeSectionOutput(summary=None)

    # Size bound, re-checked at the job (fan-out already filters): jobs queued
    # before the bound existed — or requeued across it — must not spend a
    # serialized heavy-slot generation on a section that is its own summary.
    # Stamped jobs only: an explicitly requested (unstamped) single-section
    # summary still runs regardless of size.
    if (
        input_data.parse_generation is not None
        and len(text.strip()) < _MIN_SUMMARY_CHARS
    ):
        logger.info(
            f"summarize_section: section {section.id} has {len(text.strip())} "
            f"chars (< {_MIN_SUMMARY_CHARS}) — small enough to read directly; "
            f"skipping"
        )
        return SummarizeSectionOutput(summary=None)

    if len(text) > _MAX_SUMMARY_INPUT_CHARS:
        logger.warning(
            f"summarize_section: section {section.id} text ({len(text)} chars) "
            f"exceeds the context budget — truncating to "
            f"{_MAX_SUMMARY_INPUT_CHARS} chars"
        )
        text = text[:_MAX_SUMMARY_INPUT_CHARS] + "\n\n[…truncated for length]"

    # Reasoning OFF (apply_reasoning_flag): a routing blurb needs no thinking
    # prelude, and a thinking model can burn its whole token budget reasoning
    # and return empty content (observed live on vision verify). With thinking
    # disabled, max_tokens=1024 is ample for a ≤300-char blurb while cutting
    # the old unbounded 8192 budget 8×.
    model = apply_reasoning_flag(
        await provision_langchain_model(
            text, None, "transformation",
            max_tokens=1024, num_ctx=_SUMMARY_NUM_CTX,
        ),
        False,
    )

    # Shares the Ollama gate's single heavy slot with vision verify — see the
    # lane comment in `verify_commands.verify_clean_section`. `provision_*` may
    # swap the transformation model for `large_context_model` on long sections;
    # both defaults resolve to the same local provider, so either is heavy.
    defaults = await model_manager.get_defaults()
    lane = await heavy_lane_for(defaults.default_transformation_model)
    if lane is heavy_lane and heavy_lane.locked():
        await report_job_progress(job_id, "Waiting for the local model")

    try:
        async with lane:
            await report_job_progress(job_id, "Summarizing section")
            response = await model.ainvoke(
                [HumanMessage(content=f"{_SUMMARY_INSTRUCTION}\n\n{text}")]
            )
    except Exception as e:
        # BLOCKED, not BROKEN: the heavy slot was busy. This command's retry
        # budget is 3 attempts × 5s fixed — it cannot outlast a single 35B model
        # load, so a swap used to march it straight to `failed`. Requeue instead.
        if is_resource_busy(e) and input_data.requeue_count < MAX_REQUEUES:
            await report_job_progress(job_id, "Waiting for the local model")
            await requeue_job(
                "open_notebook",
                "summarize_section",
                {
                    "source_section_id": input_data.source_section_id,
                    "source_id": input_data.source_id,
                    "parse_generation": input_data.parse_generation,
                    "requeue_count": input_data.requeue_count + 1,
                },
            )
            logger.info(
                f"summarize_section: section {section.id} requeued "
                f"(heavy slot busy, attempt {input_data.requeue_count + 1})"
            )
            return SummarizeSectionOutput(summary=None)

        # Classify raw provider errors (502s, timeouts, auth…) into typed
        # exceptions with user-friendly messages. Transient classes
        # (ExternalServiceError/NetworkError/RateLimitError) are still retried
        # by surreal-commands; ConfigurationError stays permanent (stop_on).
        exc_class, message = classify_error(e)
        raise exc_class(f"Chapter summary failed: {message}") from e
    summary = clean_thinking_content(extract_text_content(response.content))

    if not summary or not summary.strip():
        logger.warning(
            f"summarize_section: section {section.id}: model returned empty summary"
        )
        return SummarizeSectionOutput(summary=None)

    await report_job_progress(job_id, "Saving summary")
    had_summary = bool(section.summary and section.summary.strip())
    section.summary = summary
    await section.save()
    logger.info(
        f"summarize_section: wrote summary ({len(summary)} chars) for section "
        f"{section.id}"
    )

    # --- Event-driven abstract trigger ---
    # The job that fills the LAST missing summary submits the doc abstract.
    # Submitting the abstract at fan-out time (the old design) gave it a
    # ~10-minute retry window to outlast N sequential local-LLM summaries —
    # hours on a real book — so it always exhausted its retries and failed
    # (observed live: 8 attempts / 4m43s, then "472/472 not yet summarized").
    # ``had_summary`` guards manual re-runs: overwriting existing summaries
    # never re-triggers per-section (regeneration paths submit the abstract
    # themselves, and its readiness gate passes instantly there). A concurrent
    # double-fire is harmless — the abstract is idempotent by design.
    if not had_summary and section.source:
        try:
            remaining = await _remaining_unsummarized(str(section.source))
            if remaining == 0:
                cmd_id = submit_command(
                    "open_notebook",
                    "generate_source_abstract",
                    {"source_id": str(section.source)},
                )
                logger.info(
                    f"summarize_section: last pending summary written — "
                    f"submitted generate_source_abstract for {section.source}: "
                    f"{cmd_id}"
                )
        except Exception as exc:
            # Never fail (or retry) a successful summary over the trigger.
            logger.warning(
                f"summarize_section: abstract auto-trigger failed for "
                f"{section.source}: {exc}"
            )

    return SummarizeSectionOutput(summary=summary)


@command(
    "summarize_source",
    app="open_notebook",
    # Same eventual-consistency posture as verify_clean_source: raise-to-retry
    # until the build_sections job for this source reaches a terminal state AND
    # the tree is non-empty. The old design (Source.summarize_sections() called
    # inline from the ingest graph) sampled the tree at submit time — observed
    # live as an EMPTY tree 0.05s after build_sections was submitted, so zero
    # summarize_section jobs were ever created for a 472-section book.
    retry={
        "max_attempts": 8,
        "wait_strategy": "exponential_jitter",
        "wait_min": 10,
        "wait_max": 120,
        "stop_on": [ValueError, ConfigurationError],
    },
)
async def summarize_source(
    input_data: SummarizeSourceInput,
) -> SummarizeSourceOutput:
    """Fan out one ``summarize_section`` job per section of a source.

    Orchestrator counterpart to ``verify_clean_source``: waits (via
    raise-to-retry) for chaptering to finish, then submits per-section summary
    jobs. The document abstract is NOT submitted here — the summarize_section
    job that writes the last missing summary triggers it (event-driven), so the
    abstract can't lose a retry-window race against hours of local-LLM
    summarization. Per-section submit is wrapped so one failure can't poison
    the rest.
    """
    start_time = time.time()
    job_id = _job_id(input_data)
    await report_job_progress(job_id, "Checking chaptering status")

    source = await Source.get(input_data.source_id)
    if not source:
        raise ValueError(f"Source '{input_data.source_id}' not found")

    if await blocks_in_flight(input_data.source_id):
        # Defer, don't retry — build_blocks resubmits us after it rebuilds the
        # tree. See commands/verify_commands.py::blocks_in_flight.
        note = (
            f"Deferred: block parse (build_blocks) still in flight for source "
            f"{input_data.source_id}; it will resubmit summarize_source once "
            f"the final section tree exists."
        )
        logger.info(f"summarize_source: {note}")
        return SummarizeSourceOutput(
            success=True,
            source_id=input_data.source_id,
            jobs_submitted=0,
            error_message=note,
        )

    if await chaptering_in_flight(input_data.source_id):
        raise RuntimeError(
            f"Chaptering (build_sections) still in flight for source "
            f"{input_data.source_id} — section tree incomplete; will retry"
        )

    tree = await source.get_sections()
    if not tree:
        raise RuntimeError(
            f"No sections yet for source {input_data.source_id} — "
            f"chaptering may still be running; will retry"
        )

    # Tiered-summary policy: fan out only for level ≤ _MAX_SUMMARY_LEVEL nodes
    # holding ≥ _MIN_SUMMARY_CHARS of text — deeper or smaller sections fit in
    # a single get_section call and don't need summaries.
    section_ids = _summary_target_ids(tree)

    if not section_ids:
        # A real (non-empty) tree where nothing qualifies — every section is
        # small enough to read directly. Nothing will event-trigger the
        # abstract, and with zero summaries it would skip anyway; this is a
        # completed run, not a retryable wait.
        note = (
            f"No section of source {input_data.source_id} needs a summary "
            f"(each is deeper than level {_MAX_SUMMARY_LEVEL} or under "
            f"{_MIN_SUMMARY_CHARS} chars); nothing to do."
        )
        logger.info(f"summarize_source: {note}")
        return SummarizeSourceOutput(
            success=True,
            source_id=input_data.source_id,
            sections_found=0,
            jobs_submitted=0,
            error_message=note,
        )

    await report_job_progress(
        job_id, "Submitting section summary jobs", sections=len(section_ids)
    )
    jobs_submitted = 0
    section_titles = _flatten_section_titles(tree)
    for section_id in section_ids:
        try:
            cmd_id = submit_command(
                "open_notebook",
                "summarize_section",
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
            logger.debug(
                f"summarize_source: submitted summarize_section for "
                f"{section_id}: {cmd_id}"
            )
            jobs_submitted += 1
        except Exception as exc:
            logger.warning(
                f"summarize_source: failed to submit summarize_section for "
                f"{section_id}: {exc}"
            )

    processing_time = time.time() - start_time
    logger.info(
        f"summarize_source: {len(section_ids)} sections, "
        f"{jobs_submitted} jobs submitted for {input_data.source_id} "
        f"in {processing_time:.2f}s"
    )
    return SummarizeSourceOutput(
        success=True,
        source_id=input_data.source_id,
        sections_found=len(section_ids),
        jobs_submitted=jobs_submitted,
    )


@command(
    "generate_source_abstract",
    app="open_notebook",
    # Coordination race: this is submitted immediately after fanning out one
    # summarize_section job per section (Source.summarize_sections()) — those
    # jobs haven't necessarily completed yet. Retry-until-ready, mirroring the
    # eventual-consistency pattern verify_clean_source uses for build_sections
    # (commands/verify_commands.py). Summarization is N sequential LLM calls
    # (potentially slow on a single local GPU, per Decision "cost/speed not a
    # constraint"), so this window is wider than verify_clean_source's.
    # AUTO-DECIDED default — see B3 chunk report for the fork.
    retry={
        "max_attempts": 8,
        "wait_strategy": "exponential_jitter",
        "wait_min": 15,
        "wait_max": 120,
        "stop_on": [ValueError, ConfigurationError],
    },
)
async def generate_source_abstract(
    input_data: GenerateSourceAbstractInput,
) -> GenerateSourceAbstractOutput:
    """Roll up all section summaries into one document-level abstract.

    Idempotent: any existing ``abstract`` SourceInsight is deleted before the
    new one is added, so re-running (auto-retry or a manual re-run via
    ``Source.summarize_sections()``) never duplicates it.
    """
    job_id = _job_id(input_data)
    await report_job_progress(job_id, "Loading section summaries")

    source = await Source.get(input_data.source_id)
    if not source:
        raise ValueError(f"Source '{input_data.source_id}' not found")

    tree = await source.get_sections()
    if not tree:
        raise RuntimeError(
            f"No sections yet for source {input_data.source_id} — chaptering "
            "may still be in flight; will retry"
        )

    rows = _flatten_sections_for_abstract(tree)
    # Tiered-summary policy: only level ≤ _MAX_SUMMARY_LEVEL nodes are
    # expected to have summaries (readiness) or contribute to the roll-up
    # (deeper summaries may exist from older runs — routing never reads them).
    tier_rows = [r for r in rows if r["level"] <= _MAX_SUMMARY_LEVEL]
    # Only sections that summarize_source actually fans out over are awaited:
    # level ≤ _MAX_SUMMARY_LEVEL AND ≥ _MIN_SUMMARY_CHARS of text. Waiting on
    # anything else (heading-only parents, sub-threshold sections) would retry
    # to exhaustion for summaries that never come.
    pending = [
        r["title"]
        for r in tier_rows
        if r["text_len"] >= _MIN_SUMMARY_CHARS
        and not (r["summary"] and r["summary"].strip())
    ]
    if pending:
        raise RuntimeError(
            f"{len(pending)}/{len(tier_rows)} section(s) with text not yet "
            f"summarized for source {input_data.source_id} "
            f"(e.g. {pending[0]!r}); will retry"
        )

    summarized_rows = [r for r in tier_rows if r["summary"] and r["summary"].strip()]
    if not summarized_rows:
        note = "No section summaries available to build an abstract — skipped."
        logger.warning(f"generate_source_abstract: source {source.id}: {note}")
        return GenerateSourceAbstractOutput(
            success=False, source_id=input_data.source_id, error_message=note
        )

    rollup_text = "\n\n".join(
        f"## {r['title']}\n{r['summary']}" for r in summarized_rows
    )
    prompt = (
        "Based on these chapter summaries, write a concise abstract for the "
        f"document.\n\n{rollup_text}"
    )
    await report_job_progress(job_id, "Generating abstract")
    # Same knobs as summarize_section: the roll-up over ~170 blurbs (~13K
    # tokens) overflows the 8192 default num_ctx, and a thinking prelude risks
    # eating the output budget (empty abstract).
    model = apply_reasoning_flag(
        await provision_langchain_model(
            rollup_text, None, "transformation",
            max_tokens=8192, num_ctx=_SUMMARY_NUM_CTX,
        ),
        False,
    )
    try:
        response = await model.ainvoke([HumanMessage(content=prompt)])
    except Exception as e:
        exc_class, message = classify_error(e)
        raise exc_class(f"Document abstract failed: {message}") from e
    abstract_text = clean_thinking_content(extract_text_content(response.content))

    if not abstract_text or not abstract_text.strip():
        note = "Model returned an empty abstract — skipped (no insight written)."
        logger.warning(f"generate_source_abstract: source {source.id}: {note}")
        return GenerateSourceAbstractOutput(
            success=False, source_id=input_data.source_id, error_message=note
        )

    await report_job_progress(job_id, "Saving abstract")
    # --- Idempotency: replace any existing abstract insight, never duplicate ---
    existing = await source.get_insights()
    for insight in existing:
        if insight.insight_type == "abstract":
            try:
                await insight.delete()
            except Exception as exc:
                logger.warning(
                    f"generate_source_abstract: failed to delete stale abstract "
                    f"insight {insight.id}: {exc}"
                )

    await source.add_insight("abstract", abstract_text)
    logger.info(
        f"generate_source_abstract: wrote abstract ({len(abstract_text)} chars) "
        f"for source {source.id}"
    )

    return GenerateSourceAbstractOutput(
        success=True, source_id=input_data.source_id, abstract=abstract_text
    )
