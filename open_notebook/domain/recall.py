"""Study-memory recall search (study-memory Track B, chunk B1).

Python wrapper over ``fn::recall_search`` (migration 28, Track A chunk A1) —
kept in its own module, deliberately separate from ``domain/notebook.py``, so
Track B never touches a file Track A owns (see coordinator decision 10).

Consumers: the two chat tools in ``open_notebook.ai.chat_tools``
(``search_past_discussions`` / ``get_past_discussion``), the tool-loop capture
in ``open_notebook.graphs.chat._run_tool_loop``, and (chunk B2) the source-chat
tool binding + Claude-agent tool_uses capture. All of them must see the SAME
normalized shape — the coordinator's RecallRef contract:

    {kind, title, session_id, scope, source_id, notebook_id, message_id,
     annotation_id, page, quote, similarity}

``search_past_discussions`` (chat_tools.py) is the STRUCTURAL spoiler guard:
it may only ever return the fields above — never ``gist``, the annotation
``note``, or any other answer text. ``get_exchange_content`` below is the ONLY
place full content is exposed, and only on an explicit second tool call.
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.exceptions import (
    DatabaseOperationError,
    InvalidInputError,
    NotFoundError,
)
from open_notebook.utils.embedding import generate_embedding

# Coordinator decision 7 (Q-dedup-cap).
_MAX_RECALL_REFS = 10

# The RecallRef contract's exact key set, in contract order. Every normalized
# row carries every one of these keys (None where the fn left it NONE) so
# downstream consumers (tools, checkpoint kwargs, API models, frontend types)
# never have to guard for a missing key.
_RECALL_REF_FIELDS = (
    "kind",
    "title",
    "session_id",
    "scope",
    "source_id",
    "notebook_id",
    "message_id",
    "annotation_id",
    "page",
    "quote",
    "similarity",
)

# Fields that come back from SurrealDB as record links (or already-stringified
# RecordIDs via repo_query's parse_record_ids) — stringify defensively so a
# raw RecordID can never leak into the contract.
_RECORD_ID_FIELDS = ("session_id", "source_id", "notebook_id", "annotation_id")


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _normalize_recall_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one raw ``fn::recall_search`` row to the RecallRef contract:
    every contract key present, record-id-shaped fields stringified.

    Also carries the row's own raw ``id`` (``chat_exchange:...`` /
    ``source_annotation:...``) as an EXTRA key beyond the 11-field contract.
    This is NOT part of the frontend wire contract (Track C's RecallRef type
    never sees it — B3's serialization only copies known
    ``RecallRef.model_fields`` keys, silently dropping this one) — it exists
    purely so ``get_past_discussion`` (chat_tools.py) has something to fetch
    by for an "exchange" row. Annotation rows don't strictly need it since
    ``annotation_id`` already equals the row's own id, but carrying it
    uniformly keeps the two kinds symmetric.
    """
    ref: Dict[str, Any] = {field: row.get(field) for field in _RECALL_REF_FIELDS}
    for field in _RECORD_ID_FIELDS:
        ref[field] = _stringify(ref[field])
    ref["message_id"] = _stringify(ref["message_id"])
    ref["similarity"] = float(ref["similarity"]) if ref["similarity"] is not None else 0.0
    ref["id"] = _stringify(row.get("id"))
    return ref


def _dedupe_key(ref: Dict[str, Any]) -> Optional[tuple]:
    """The dedupe identity for one ref (coordinator decision 7): session_id
    for an exchange, annotation_id for an annotation. Refs missing the
    relevant key (shouldn't happen against a healthy fn, but tests/older rows
    might) are never deduped against each other — each stays distinct."""
    if ref.get("kind") == "exchange" and ref.get("session_id"):
        return ("exchange", ref["session_id"])
    if ref.get("kind") == "annotation" and ref.get("annotation_id"):
        return ("annotation", ref["annotation_id"])
    return None


def dedupe_and_cap_recall_refs(
    refs: List[Dict[str, Any]], limit: int = _MAX_RECALL_REFS
) -> List[Dict[str, Any]]:
    """Dedupe a list of (already-normalized) RecallRef dicts by session_id
    (exchange) / annotation_id (annotation), keeping the highest-similarity
    row per key, then sort by similarity desc and cap at ``limit``.

    Shared by: ``recall_search`` below, the tool-loop capture in
    ``graphs/chat.py``, and (chunk B2) the source-chat tool loop + Claude-agent
    tool_uses capture — all three must call this SAME function so caps/dedupe
    stay consistent across every model path.
    """
    best: Dict[tuple, Dict[str, Any]] = {}
    unkeyed: List[Dict[str, Any]] = []
    for ref in refs:
        key = _dedupe_key(ref)
        if key is None:
            unkeyed.append(ref)
            continue
        existing = best.get(key)
        if existing is None or (ref.get("similarity") or 0) > (existing.get("similarity") or 0):
            best[key] = ref
    deduped = list(best.values()) + unkeyed
    deduped.sort(key=lambda r: r.get("similarity") or 0, reverse=True)
    return deduped[:limit]


async def recall_search(
    query: str, limit: int = _MAX_RECALL_REFS, minimum_score: float = 0.35
) -> List[Dict[str, Any]]:
    """Embed ``query`` and search ``fn::recall_search`` (chat_exchange +
    source_annotation, migration 28) for related past study material.

    Returns a list of RecallRef-contract dicts, deduped and capped at
    ``limit`` (see ``dedupe_and_cap_recall_refs``). Metadata only — never
    includes ``gist``/``note``/answer text; see ``get_exchange_content`` for
    full content.

    ``minimum_score`` default of 0.35 is a documented guess
    (coordinator Open Question Q-min-score) — not tuned against real
    embeddings from this environment.
    """
    if not query:
        raise InvalidInputError("Recall query cannot be empty")
    try:
        embedding = await generate_embedding(query)
        rows = await repo_query(
            """
            SELECT * FROM fn::recall_search($query, $match_count, $min_similarity);
            """,
            {
                "query": embedding,
                "match_count": limit,
                "min_similarity": minimum_score,
            },
        )
        normalized = [
            _normalize_recall_row(row) for row in (rows or []) if isinstance(row, dict)
        ]
        return dedupe_and_cap_recall_refs(normalized, limit)
    except Exception as e:
        logger.error(f"Error performing recall search: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)


async def get_exchange_content(ref_id: str) -> Dict[str, Any]:
    """Fetch the FULL content of one recall reference, by its raw id
    (``chat_exchange:...`` or ``source_annotation:...``, as returned in a
    RecallRef's own row — NOT exposed on the RecallRef contract itself).

    This is the ONLY place full content (gist / annotation note) is exposed —
    the structural half of the spoiler guard alongside ``recall_search``'s
    metadata-only rows. Called only from ``get_past_discussion``
    (``chat_tools.py``), on an explicit second tool call.

    Returns ``{question, gist, session_id, title}`` for a chat_exchange id,
    ``{quote, note, tags, page, source_id}`` for a source_annotation id.
    """
    if not ref_id:
        raise InvalidInputError("Recall ref id cannot be empty")
    table = ref_id.split(":", 1)[0] if ":" in ref_id else ref_id
    try:
        if table == "chat_exchange":
            rows = await repo_query(
                """
                SELECT question, gist, session AS session_id, session.title AS title
                FROM $id;
                """,
                {"id": ensure_record_id(ref_id)},
            )
            if not rows:
                raise NotFoundError(f"chat_exchange not found: {ref_id}")
            row = rows[0]
            return {
                "question": row.get("question"),
                "gist": row.get("gist"),
                "session_id": _stringify(row.get("session_id")),
                "title": row.get("title"),
            }
        if table == "source_annotation":
            rows = await repo_query(
                """
                SELECT quote, note, tags, page, source AS source_id
                FROM $id;
                """,
                {"id": ensure_record_id(ref_id)},
            )
            if not rows:
                raise NotFoundError(f"source_annotation not found: {ref_id}")
            row = rows[0]
            return {
                "quote": row.get("quote"),
                "note": row.get("note"),
                "tags": row.get("tags"),
                "page": row.get("page"),
                "source_id": _stringify(row.get("source_id")),
            }
        raise InvalidInputError(f"Unsupported recall ref id: {ref_id}")
    except (InvalidInputError, NotFoundError):
        raise
    except Exception as e:
        logger.error(f"Error fetching recall ref content: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)
