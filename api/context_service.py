"""
Context service layer using API.
"""

from typing import Any, Dict, List, Optional, Tuple, Union

from loguru import logger

from api.client import api_client
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Note, Notebook, Source, SourceInsight


class ContextService:
    """Service layer for context operations using API."""

    def __init__(self):
        logger.info("Using API for context operations")

    def get_notebook_context(
        self, notebook_id: str, context_config: Optional[Dict] = None
    ) -> Union[Dict[Any, Any], List[Dict[Any, Any]]]:
        """Get context for a notebook."""
        result = api_client.get_notebook_context(
            notebook_id=notebook_id, context_config=context_config
        )
        return result


# Global service instance
context_service = ContextService()


# ---------------------------------------------------------------------------
# Shared notebook-context builder (server-side).
#
# Both POST /chat/context (api/routers/chat/execute.py) and
# POST /notebooks/{id}/context (api/routers/context.py) build the SAME per-source
# / per-note context digest for a notebook. This is the single source of that
# logic (db-design §6 waste #10 — the two endpoints were near-verbatim
# duplicates), and it carries the read-path hygiene it enables:
#   - the "insights" (short) path fetches the metadata-only source record
#     (Source.get_meta — OMIT full_text/page_map/page_labels) since a short
#     digest never reads full_text (db-design §6 waste #3/#5);
#   - the default "all sources" path batches the per-source insight fetch into
#     ONE `SELECT ... WHERE source IN $ids` instead of N get_insights round trips
#     (db-design §6 waste #6).
# The "full content" (long) path still fetches the full record because
# Source.get_context(context_size="long") falls back to raw full_text for
# un-chaptered sources (Decision #12), so behavior is preserved exactly.
# ---------------------------------------------------------------------------


def _prefix(id_: str, table: str) -> str:
    """Ensure ``id_`` carries the ``table:`` prefix."""
    return id_ if id_.startswith(f"{table}:") else f"{table}:{id_}"


async def _insights_by_source(
    source_ids: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch all sources' insights in one query, grouped by source id string.

    Replaces the per-source ``Source.get_insights()`` N+1 (db-design §6 waste
    #6). Each value is the list of ``SourceInsight.model_dump()`` dicts, matching
    exactly what ``Source.get_context(context_size="short")`` embeds.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    if not source_ids:
        return grouped
    rows = await repo_query(
        "SELECT * FROM source_insight WHERE source IN $ids",
        {"ids": [ensure_record_id(sid) for sid in source_ids]},
    )
    for row in rows:
        key = str(row.get("source"))
        grouped.setdefault(key, []).append(SourceInsight(**row).model_dump())
    return grouped


async def build_context_data(
    notebook: Notebook,
    context_config: Optional[Dict[str, Dict[str, str]]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """Assemble source + note context for a notebook.

    Returns ``(sources_context, notes_context, concatenated_content)``. Callers
    wrap these into their own response models and compute token/char counts from
    the concatenated string. Behavior matches the original inline logic exactly:

    - with a config: per-source ``"insights"`` → short / ``"full content"`` →
      long, ``"not in"`` / anything else → skipped; notes only for
      ``"full content"`` → long.
    - without a config: every source short, every note short.

    Per-item errors are swallowed with a warning (unchanged), so one bad record
    never fails the whole context build.
    """
    sources_context: List[Dict[str, Any]] = []
    notes_context: List[Dict[str, Any]] = []
    total_content = ""

    if context_config:
        logger.info(f"Building context from context_config for notebook {notebook.id}")
        logger.info(f"Context config sources: {context_config.get('sources', {})}")
        logger.info(f"Context config notes: {context_config.get('notes', {})}")
        for source_id, status in (context_config.get("sources") or {}).items():
            if "not in" in status:
                continue

            try:
                full_source_id = _prefix(source_id, "source")

                if "insights" in status:
                    # short digest never reads full_text → metadata-only fetch
                    try:
                        source = await Source.get_meta(full_source_id)
                    except Exception:
                        continue
                    source_context = await source.get_context(context_size="short")
                elif "full content" in status:
                    # long digest's no-outline fallback (Decision #12) still needs
                    # full_text, so fetch the full record here
                    try:
                        source = await Source.get(full_source_id)
                    except Exception:
                        continue
                    source_context = await source.get_context(context_size="long")
                else:
                    logger.warning(f"Source {source_id} with status '{status}' doesn't match 'insights' or 'full content'")
                    continue

                logger.info(f"Added source {source_id} to context with status '{status}'")
                sources_context.append(source_context)
                total_content += str(source_context)
            except Exception as e:
                logger.warning(f"Error processing source {source_id}: {str(e)}")
                continue

        for note_id, status in (context_config.get("notes") or {}).items():
            if "not in" in status:
                continue

            try:
                full_note_id = _prefix(note_id, "note")
                note = await Note.get(full_note_id)
                if not note:
                    continue

                if "full content" in status:
                    note_context = note.get_context(context_size="long")
                    notes_context.append(note_context)
                    total_content += str(note_context)
            except Exception as e:
                logger.warning(f"Error processing note {note_id}: {str(e)}")
                continue
    else:
        # Default: every source short, every note short.
        sources = await notebook.get_sources()
        logger.info(f"Fetched {len(sources)} sources for notebook {notebook.id}")
        insights_by_source = await _insights_by_source(
            [s.id for s in sources if s.id]
        )
        for source in sources:
            try:
                # Inline of Source.get_context(context_size="short") using the
                # batch-fetched insights (waste #6: was N get_insights queries).
                source_context = {
                    "id": source.id,
                    "title": source.title,
                    "insights": insights_by_source.get(str(source.id), []),
                }
                sources_context.append(source_context)
                total_content += str(source_context)
            except Exception as e:
                logger.warning(f"Error processing source {source.id}: {str(e)}")
                continue

        notes = await notebook.get_notes()
        for note in notes:
            try:
                note_context = note.get_context(context_size="short")
                notes_context.append(note_context)
                total_content += str(note_context)
            except Exception as e:
                logger.warning(f"Error processing note {note.id}: {str(e)}")
                continue

    logger.info(f"Context build complete: {len(sources_context)} sources, {len(notes_context)} notes, {len(total_content)} total chars")
    return sources_context, notes_context, total_content
