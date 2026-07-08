"""
Per-section summaries + document abstract for Open Notebook (Track B, Chunk B3).

Three commands, layered on top of A3's section tree and B2's verify-clean layer:
  - ``summarize_source``         : fan-out orchestrator — waits (raise-to-retry)
    for chaptering to reach a terminal state, then submits one
    ``summarize_section`` job per section. Mirrors ``verify_clean_source``.
  - ``summarize_section``        : summarize one ``source_section`` concisely.
    Prefers ``cleaned_content`` (B2's vision-verified layer) but falls back to
    the raw parsed ``content`` when verify-clean hasn't landed yet (or was
    skipped) — verify and summarize are independent fire-and-forget triggers
    with no ordering guarantee. The job that writes the LAST missing summary
    submits ``generate_source_abstract`` (event-driven trigger).
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

# Shared race-guard + tree-flatten helpers live with the B2 orchestrator; both
# fan-outs must gate on the same "chaptering reached a terminal state" predicate.
from commands.verify_commands import (
    _chaptering_in_flight,
    _flatten_section_titles,
)
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Source, SourceSection
from open_notebook.exceptions import ConfigurationError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content

# ---------------------------------------------------------------------------
# Pydantic I/O models
# ---------------------------------------------------------------------------


class SummarizeSectionInput(CommandInput):
    source_section_id: str


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


# to-fix/003 defense-in-depth: hard cap on summarizer input. ~300K chars is
# ≈75K tokens — comfortable headroom in a 100K-token context. After the
# section-bounding fix in commands/section_commands.py nothing should hit it.
_MAX_SUMMARY_INPUT_CHARS = 300_000

# Tiered-summary policy (2026-07-05): summaries exist for ROUTING — they earn
# their keep where reading the real text is expensive (level 1 chapters avg
# ~65K chars ≈ 16 get_section calls; level 2 sections avg ~9.5K). At level 3+
# the section itself fits in a single get_section call, so a dense summary
# costs nearly as much context as the real text while adding outline bloat.
# Fan-out, the abstract readiness gate, and the abstract roll-up all use this
# bound. summarize_section itself stays level-agnostic (explicit per-section
# requests still work).
_MAX_SUMMARY_LEVEL = 2


def _summary_target_ids(nodes: List[Dict]) -> List[str]:
    """Depth-first ids of nodes at level ≤ ``_MAX_SUMMARY_LEVEL``."""
    ids: List[str] = []
    for node in nodes:
        nid = node.get("id")
        if nid and (node.get("level") or 1) <= _MAX_SUMMARY_LEVEL:
            ids.append(str(nid))
        ids.extend(_summary_target_ids(node.get("children") or []))
    return ids


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _flatten_sections_for_abstract(nodes: List[Dict]) -> List[Dict]:
    """Depth-first flatten of a ``get_sections()`` tree into ordered rows.

    Each row carries ``title``, ``summary``, and ``has_text`` (whether the
    section has any raw text worth summarizing — ``cleaned_content`` or
    ``content``, non-blank). Used both to build the roll-up prompt and to
    gate readiness without deadlocking on structural (heading-only) parent
    nodes that never receive a summary by design.
    """
    flat: List[Dict] = []
    for node in nodes:
        text = node.get("cleaned_content") or node.get("content") or ""
        flat.append(
            {
                "title": node.get("title") or "(untitled)",
                "level": node.get("level") or 1,
                "summary": node.get("summary"),
                "has_text": bool(text.strip()),
            }
        )
        flat.extend(_flatten_sections_for_abstract(node.get("children") or []))
    return flat


async def _remaining_unsummarized(source_id: str) -> int:
    """Count text-bearing sections of a source that still lack a summary.

    Mirrors ``generate_source_abstract``'s readiness gate (``has_text`` =
    non-blank ``cleaned_content`` or ``content``; heading-only nodes never get
    a summary and never count; level > ``_MAX_SUMMARY_LEVEL`` nodes are outside
    the tiered-summary policy and never count either). Used by the
    event-driven abstract trigger in ``summarize_section``.
    """
    rows = await repo_query(
        """
        SELECT count() AS n FROM source_section
        WHERE source = $src
          AND level <= $max_level
          AND (
              string::len(string::trim(cleaned_content ?? '')) > 0
              OR string::len(string::trim(content ?? '')) > 0
          )
          AND string::len(string::trim(summary ?? '')) == 0
        GROUP ALL
        """,
        {"src": ensure_record_id(source_id), "max_level": _MAX_SUMMARY_LEVEL},
    )
    return int(rows[0].get("n", 0)) if rows else 0


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
    section = await SourceSection.get(input_data.source_section_id)
    if not section:
        raise ValueError(
            f"SourceSection '{input_data.source_section_id}' not found"
        )

    text = section.cleaned_content or section.content
    if not text or not text.strip():
        logger.info(
            f"summarize_section: section {section.id} has no text; skipping"
        )
        return SummarizeSectionOutput(summary=None)

    if len(text) > _MAX_SUMMARY_INPUT_CHARS:
        logger.warning(
            f"summarize_section: section {section.id} text ({len(text)} chars) "
            f"exceeds the context budget — truncating to "
            f"{_MAX_SUMMARY_INPUT_CHARS} chars"
        )
        text = text[:_MAX_SUMMARY_INPUT_CHARS] + "\n\n[…truncated for length]"

    model = await provision_langchain_model(
        text, None, "transformation", max_tokens=8192
    )
    try:
        response = await model.ainvoke(
            [HumanMessage(content=f"Summarize this document section concisely:\n\n{text}")]
        )
    except Exception as e:
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

    source = await Source.get(input_data.source_id)
    if not source:
        raise ValueError(f"Source '{input_data.source_id}' not found")

    if await _chaptering_in_flight(input_data.source_id):
        raise RuntimeError(
            f"Chaptering (build_sections) still in flight for source "
            f"{input_data.source_id} — section tree incomplete; will retry"
        )

    tree = await source.get_sections()
    # Tiered-summary policy: fan out only for level ≤ _MAX_SUMMARY_LEVEL —
    # deeper nodes fit in a single get_section call and don't need summaries.
    section_ids = _summary_target_ids(tree)

    if not section_ids:
        raise RuntimeError(
            f"No sections yet for source {input_data.source_id} — "
            f"chaptering may still be running; will retry"
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
    pending = [
        r["title"]
        for r in tier_rows
        if r["has_text"] and not (r["summary"] and r["summary"].strip())
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
    model = await provision_langchain_model(
        rollup_text, None, "transformation", max_tokens=8192
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
