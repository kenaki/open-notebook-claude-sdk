"""Scoped vector search + one-round-trip hybrid retrieval (db-design.md 3d-e).

Two entry points, both source-scopeable:

* ``scoped_vector_search`` — brute-force cosine pre-filtered to a set of sources
  via ``fn::vector_search_scoped`` (migration 24). Cost is per-source, not
  per-corpus, so no vector index is needed at current scale.
* ``hybrid_search`` — dense (scoped cosine) + sparse (BM25 full-text) in ONE
  round trip, fused in Python with Reciprocal Rank Fusion. ``search::rrf`` is
  SurrealDB 3.0+; the Python fusion below is the documented default and a
  one-line swap later.

SurrealDB python SDK quirk (live-verified on 2.6.5): ``connection.query()``
returns only the FIRST statement's result, so a bare ``LET; LET; RETURN``
multi-statement yields ``None``. The hybrid query is therefore a single
top-level block expression ``RETURN { LET ...; LET ...; RETURN {...}; }`` — one
statement, one round trip, one ``{vec, ft}`` object back.
"""

from typing import Any, Dict, List, Optional

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.utils.embedding import generate_embedding

# RRF constant. Larger = flatter (rank differences matter less). 60 is the
# canonical default from the original Cormack et al. RRF paper.
RRF_K = 60

# One statement (block expression) so the SDK returns the inner RETURN's object.
# $vec: scoped brute-force cosine (fn::vector_search_scoped, migration 24).
# $ft:  BM25 full-text, planner-pinned to the BM25 index, scoped by the same
#       optional source list ($sources IS NONE OR source IN $sources — verified
#       to keep the idx_source_embed_chunk plan on 2.6.5, Q-ft-scope-index).
_HYBRID_QUERY = """
RETURN {
    LET $vec = (SELECT * FROM fn::vector_search_scoped($embed, $k, $sources, $min));
    LET $ft = (
        SELECT source, order, content, page_number, bbox, block_start, block_end,
               search::score(1) AS score
        FROM source_embedding WITH INDEX idx_source_embed_chunk
        WHERE content @1@ $q AND ($sources IS NONE OR source IN $sources)
        ORDER BY score DESC LIMIT $k
    );
    RETURN { vec: $vec, ft: $ft };
};
"""


def _norm_vec(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a fn::vector_search_scoped row to the fused-result shape."""
    sid = str(row.get("id")) if row.get("id") is not None else None
    return {
        "id": sid,
        "parent_id": sid,
        "title": row.get("title"),
        "matches": row.get("matches"),
        "content": None,
        "page_number": row.get("page_number"),
        "bbox": row.get("bbox"),
        "block_start": row.get("block_start"),
        "block_end": row.get("block_end"),
        "similarity": row.get("similarity"),
    }


def _norm_ft(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a BM25 source_embedding row to the fused-result shape."""
    sid = str(row.get("source")) if row.get("source") is not None else None
    content = row.get("content")
    return {
        "id": sid,
        "parent_id": sid,
        "title": None,
        "matches": [content] if content is not None else None,
        "content": content,
        "page_number": row.get("page_number"),
        "bbox": row.get("bbox"),
        "block_start": row.get("block_start"),
        "block_end": row.get("block_end"),
        "score": row.get("score"),
    }


def _merge(reps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge duplicate representatives of one key, preferring first non-None.

    Reps are appended vector-arm-first, so the dense row (which carries title +
    matches + bbox) wins ties and the sparse row fills any gaps (e.g. content).
    """
    merged: Dict[str, Any] = {}
    for rep in reps:
        for key, value in rep.items():
            if merged.get(key) is None and value is not None:
                merged[key] = value
    return merged


def reciprocal_rank_fusion(
    ranked_lists: List[List[Dict[str, Any]]],
    key,
    rrf_k: int = RRF_K,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fuse ranked result lists with Reciprocal Rank Fusion.

    Each row contributes ``1 / (rrf_k + rank)`` (rank is 1-based within its
    list) to its key's score. Rows sharing a key are deduped (their fields
    merged) and their contributions summed. Returns rows sorted by fused score
    descending, each stamped with ``score``, truncated to ``limit``.
    """
    scores: Dict[Any, float] = {}
    reps: Dict[Any, List[Dict[str, Any]]] = {}
    for rows in ranked_lists:
        for rank, row in enumerate(rows, start=1):
            k = key(row)
            if k is None:
                continue
            scores[k] = scores.get(k, 0.0) + 1.0 / (rrf_k + rank)
            reps.setdefault(k, []).append(row)

    ordered = sorted(scores, key=lambda k: scores[k], reverse=True)
    fused: List[Dict[str, Any]] = []
    for k in ordered:
        merged = _merge(reps[k])
        merged["score"] = scores[k]
        fused.append(merged)
    return fused[:limit] if limit is not None else fused


def _coerce_sources(source_ids: Optional[List[str]]):
    """Coerce optional source id strings to RecordIDs (None = unscoped)."""
    if not source_ids:
        return None
    return [ensure_record_id(s) for s in source_ids]


async def scoped_vector_search(
    keyword: str,
    source_ids: Optional[List[str]] = None,
    k: int = 10,
    min_score: float = 0.2,
) -> List[Dict[str, Any]]:
    """Source-scoped semantic search (db-design 3d).

    Embeds ``keyword`` and runs ``fn::vector_search_scoped``, pre-filtered to
    ``source_ids`` when given (else whole corpus). Rows carry
    block_start/block_end/page_number/bbox for block-anchored callers.
    """
    embed = await generate_embedding(keyword)
    rows = await repo_query(
        "SELECT * FROM fn::vector_search_scoped($embed, $k, $sources, $min);",
        {
            "embed": embed,
            "k": k,
            "sources": _coerce_sources(source_ids),
            "min": min_score,
        },
    )
    return rows or []


async def hybrid_search(
    keyword: str,
    source_ids: Optional[List[str]] = None,
    k: int = 10,
    min_score: float = 0.2,
) -> List[Dict[str, Any]]:
    """Dense + sparse retrieval fused with RRF, in one round trip (db-design 3e).

    Runs the scoped cosine arm and the BM25 full-text arm together, then fuses
    them in Python by source id. Fusing on source id unifies the two arms:
    ``fn::vector_search_scoped`` projects ``source.id`` as its row id while the
    BM25 arm carries a ``source`` link — both resolve to the same source key, so
    a source found by both retrievers is boosted, and multiple chunks of one
    source collapse to their best-ranked representative. Result rows keep
    block_start/block_end/page_number passthrough.
    """
    embed = await generate_embedding(keyword)
    result = await repo_query(
        _HYBRID_QUERY,
        {
            "embed": embed,
            "q": keyword,
            "sources": _coerce_sources(source_ids),
            "k": k,
            "min": min_score,
        },
    )
    payload = result if isinstance(result, dict) else {}
    vec_rows = [_norm_vec(r) for r in (payload.get("vec") or [])]
    ft_rows = [_norm_ft(r) for r in (payload.get("ft") or [])]

    return reciprocal_rank_fusion(
        [vec_rows, ft_rows],
        key=lambda r: r.get("id"),
        limit=k,
    )
