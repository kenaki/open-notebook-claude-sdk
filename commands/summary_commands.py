"""
Per-section summaries + document abstract for Open Notebook (Track B, Chunk B3).

Two commands, layered on top of A3's section tree and B2's verify-clean layer:
  - ``summarize_section``        : summarize one ``source_section`` concisely.
    Prefers ``cleaned_content`` (B2's vision-verified layer) but falls back to
    the raw parsed ``content`` when verify-clean hasn't landed yet (or was
    skipped) — verify and summarize are independent fire-and-forget triggers
    with no ordering guarantee.
  - ``generate_source_abstract`` : roll up every section summary into one
    document-level abstract, stored as a ``SourceInsight`` (idempotent —
    replaces any prior ``abstract`` insight rather than duplicating).

Design notes:
  - Coordinator Decision #4 (derived layers) / #7 (tiered chat context): these
    are the "chapter-summary outline" + "doc abstract" layers the chat agent
    and TOC sidebar consume instead of the raw ``full_text`` blob.
  - ``generate_source_abstract`` is submitted immediately after fanning out
    the per-section jobs (``Source.summarize_sections()``), so most of the
    time it will run *before* those jobs finish. It raises to retry (with
    backoff) until every section that actually has text has a summary —
    mirroring the eventual-consistency pattern ``verify_clean_source`` uses
    for ``build_sections`` (see ``commands/verify_commands.py``). It reads
    ``Source.get_sections()`` (not the lighter ``get_outline()``) so it can
    tell text-bearing sections apart from structural/heading-only nodes
    (e.g. a "Part I" divider immediately followed by a subheading) — those
    never get a summary by design (``summarize_section`` skips empty text),
    so requiring 100% of *outline* nodes to have a summary would deadlock.
"""
from typing import Dict, List, Optional

from langchain_core.messages import HumanMessage
from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.domain.notebook import Source, SourceSection
from open_notebook.exceptions import ConfigurationError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.text_utils import extract_text_content

# ---------------------------------------------------------------------------
# Pydantic I/O models
# ---------------------------------------------------------------------------


class SummarizeSectionInput(CommandInput):
    source_section_id: str


class SummarizeSectionOutput(CommandOutput):
    summary: Optional[str] = None


class GenerateSourceAbstractInput(CommandInput):
    source_id: str


class GenerateSourceAbstractOutput(CommandOutput):
    success: bool
    source_id: str
    abstract: Optional[str] = None
    error_message: Optional[str] = None


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
                "summary": node.get("summary"),
                "has_text": bool(text.strip()),
            }
        )
        flat.extend(_flatten_sections_for_abstract(node.get("children") or []))
    return flat


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

    model = await provision_langchain_model(
        text, None, "transformation", max_tokens=8192
    )
    response = await model.ainvoke(
        [HumanMessage(content=f"Summarize this document section concisely:\n\n{text}")]
    )
    summary = clean_thinking_content(extract_text_content(response.content))

    if not summary or not summary.strip():
        logger.warning(
            f"summarize_section: section {section.id}: model returned empty summary"
        )
        return SummarizeSectionOutput(summary=None)

    section.summary = summary
    await section.save()
    logger.info(
        f"summarize_section: wrote summary ({len(summary)} chars) for section "
        f"{section.id}"
    )

    return SummarizeSectionOutput(summary=summary)


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
    pending = [
        r["title"]
        for r in rows
        if r["has_text"] and not (r["summary"] and r["summary"].strip())
    ]
    if pending:
        raise RuntimeError(
            f"{len(pending)}/{len(rows)} section(s) with text not yet "
            f"summarized for source {input_data.source_id} "
            f"(e.g. {pending[0]!r}); will retry"
        )

    summarized_rows = [r for r in rows if r["summary"] and r["summary"].strip()]
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
    response = await model.ainvoke([HumanMessage(content=prompt)])
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
