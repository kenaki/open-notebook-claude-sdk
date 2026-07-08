"""Domain surface for the PDF block substrate (db-design.md §1–§3).

Blocks are keyed by COMPOSITE record ids ``document_block:[src_key, gen, seq]``
with **zero secondary indexes** — every hot-path read is a point-get or a
RocksDB prefix range scan that returns rows already in reading order. Parse
headers are ``source_parse:[src_key, gen]`` point-gets.

All helpers are single, param-bound ``repo_query`` / ``repo_insert`` round trips.
Composite ids read back as strings like ``document_block:['k', 1, 42]`` via
``parse_record_ids`` — callers that need the tuple can re-key from ``src_key``/
``gen``/``seq`` which are stored as plain fields too.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from surrealdb import RecordID

from open_notebook.database.repository import repo_insert, repo_query

BLOCK_TABLE = "document_block"
PARSE_TABLE = "source_parse"

# Full int64 span — wide seq bounds for a whole-generation range delete. A
# 2-element prefix band ([k, g] .. [k, g+1]) does NOT cover 3-element ids on
# 2.6.5 (verified live), so the generation band is deleted with arity-uniform
# 3-element bounds instead.
_SEQ_MIN = -9223372036854775808
_SEQ_MAX = 9223372036854775807


def block_rid(src_key: str, gen: int, seq: int) -> RecordID:
    """Composite record id for a block: ``document_block:[src_key, gen, seq]``."""
    return RecordID(BLOCK_TABLE, [src_key, gen, seq])


def parse_rid(src_key: str, gen: int) -> RecordID:
    """Composite record id for a parse header: ``source_parse:[src_key, gen]``."""
    return RecordID(PARSE_TABLE, [src_key, gen])


def _src_key(source: Any) -> str:
    """Extract the bare source key from ``source:<key>`` (or pass a key through)."""
    s = str(source)
    return s.split(":", 1)[1] if ":" in s else s


class DocumentBlock(BaseModel):
    """One typed block row (mirrors db-design §2.1). Read-only projection of a
    ``document_block`` record; composite id lives in ``id`` (string on read)."""

    id: Optional[str] = None
    source: Optional[str] = None
    gen: int
    seq: int
    page: int
    type: str
    text: Optional[str] = None
    latex: Optional[str] = None
    image_ref: Optional[str] = None
    bbox: Optional[List[float]] = None
    parent_seq: Optional[int] = None
    level: Optional[int] = None
    subtree_end: Optional[int] = None
    section_path: List[str] = []
    confidence: Optional[float] = None
    table_data: Optional[dict] = None

    @property
    def rid(self) -> RecordID:
        return block_rid(_src_key(self.source), self.gen, self.seq)


class SourceParse(BaseModel):
    """One parse-generation header row (mirrors db-design §2.2)."""

    id: Optional[str] = None
    source: Optional[str] = None
    gen: int
    parser_name: Optional[str] = None
    parser_version: Optional[str] = None
    status: Optional[str] = None
    content_hash: Optional[str] = None
    block_count: Optional[int] = None
    page_count: Optional[int] = None
    pages: Optional[list] = None
    page_index: Optional[List[List[int]]] = None
    section_index: Optional[list] = None
    error: Optional[str] = None
    created: Optional[Any] = None
    updated: Optional[Any] = None

    @property
    def rid(self) -> RecordID:
        return parse_rid(_src_key(self.source), self.gen)


# --------------------------------------------------------------------------- #
# Read helpers — all point-gets or prefix range scans, zero table scans.
# --------------------------------------------------------------------------- #


async def get_parse_header(src_key: str, gen: int) -> Optional[SourceParse]:
    """Point-get one parse header, or None."""
    rows = await repo_query(
        f"SELECT * FROM {PARSE_TABLE}:[$k, $g];",
        {"k": src_key, "g": gen},
    )
    return SourceParse(**rows[0]) if rows else None


async def get_page_blocks(
    src_key: str,
    gen: int,
    page: int,
    page_index: List[List[int]],
    include_text: bool = False,
) -> List[Dict[str, Any]]:
    """Range-scan one page's blocks (db-design §3a).

    ``page`` is 1-based; ``page_index`` is the header's ``page -> [lo, hi]`` list
    (index ``page - 1``). Overlay projection (``seq, type, page, bbox,
    parent_seq, level``) unless ``include_text``, which selects everything.
    Returns raw dicts (partial projections don't satisfy DocumentBlock).
    """
    idx = page - 1
    if idx < 0 or idx >= len(page_index):
        return []
    lo, hi = page_index[idx][0], page_index[idx][1]
    if lo > hi:
        return []
    projection = "*" if include_text else "seq, type, page, bbox, parent_seq, level"
    return await repo_query(
        f"SELECT {projection} FROM {BLOCK_TABLE}:[$k, $g, $lo]..=[$k, $g, $hi];",
        {"k": src_key, "g": gen, "lo": lo, "hi": hi},
    )


async def get_block(src_key: str, gen: int, seq: int) -> Optional[DocumentBlock]:
    """Point-get one full block, or None."""
    rows = await repo_query(
        f"SELECT * FROM {BLOCK_TABLE}:[$k, $g, $s];",
        {"k": src_key, "g": gen, "s": seq},
    )
    return DocumentBlock(**rows[0]) if rows else None


async def get_window(
    src_key: str, gen: int, seq: int, radius: int = 3
) -> List[Dict[str, Any]]:
    """Range-scan ``[seq-radius .. seq+radius]`` (db-design §3b), lo clamped at 0.

    Projects the annotation-context fields; returns raw dicts.
    """
    lo = max(seq - radius, 0)
    hi = seq + radius
    return await repo_query(
        f"SELECT seq, type, text, latex, image_ref, section_path "
        f"FROM {BLOCK_TABLE}:[$k, $g, $lo]..=[$k, $g, $hi];",
        {"k": src_key, "g": gen, "lo": lo, "hi": hi},
    )


async def get_range(
    src_key: str, gen: int, lo: int, hi: int
) -> List[Dict[str, Any]]:
    """Full range-scan of ``[lo .. hi]`` inclusive; returns raw dicts."""
    if lo > hi:
        return []
    return await repo_query(
        f"SELECT * FROM {BLOCK_TABLE}:[$k, $g, $lo]..=[$k, $g, $hi];",
        {"k": src_key, "g": gen, "lo": lo, "hi": hi},
    )


async def list_parse_headers(src_key: str) -> List[SourceParse]:
    """All parse headers for a source, oldest generation first. Small table —
    a WHERE scan on the ``source`` link is fine here (blocks use range ops)."""
    sid = RecordID("source", src_key)
    rows = await repo_query(
        f"SELECT * FROM {PARSE_TABLE} WHERE source = $sid ORDER BY gen;",
        {"sid": sid},
    )
    return [SourceParse(**r) for r in rows] if rows else []


# --------------------------------------------------------------------------- #
# Write / cleanup helpers.
# --------------------------------------------------------------------------- #


def _is_duplicate_error(exc: Exception) -> bool:
    """True if a repo_insert error is an explicit-id collision (idempotent skip)."""
    msg = str(exc).lower()
    return "already exists" in msg or "already contains" in msg


async def bulk_insert_blocks(
    records: List[Dict[str, Any]], batch_size: int = 1000
) -> int:
    """Insert block records in batches with EXPLICIT composite RecordIDs.

    Each record must carry an ``id`` (a ``RecordID`` from :func:`block_rid`).
    Crash-then-retry is idempotent — colliding ids are skipped rather than
    duplicated (db-design §4 step 4). NOTE: SurrealDB 2.6.5 reports an explicit
    composite-id collision as "already exists", which ``repo_insert``'s
    ``ignore_duplicates`` (matches only "already contains") does not swallow, so
    on such a collision we fall back to per-record inserts and skip the dupes.
    Returns the count actually inserted.
    """
    total = 0
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        try:
            inserted = await repo_insert(BLOCK_TABLE, batch, ignore_duplicates=True)
            total += len(inserted)
        except RuntimeError as exc:
            if not _is_duplicate_error(exc):
                raise
            for record in batch:
                try:
                    inserted = await repo_insert(
                        BLOCK_TABLE, [record], ignore_duplicates=True
                    )
                    total += len(inserted)
                except RuntimeError as inner:
                    if _is_duplicate_error(inner):
                        continue
                    raise
    return total


async def delete_generation(src_key: str, gen: int) -> None:
    """Range-DELETE every block of one generation.

    The generation is its own contiguous key band ``[src_key, gen, *]``; delete
    it with wide, arity-uniform 3-element seq bounds (a 2-element prefix band
    does not cover 3-element ids on 2.6.5). No index, one range op.
    """
    await repo_query(
        f"DELETE {BLOCK_TABLE}:[$k, $g, $lo]..=[$k, $g, $hi];",
        {"k": src_key, "g": gen, "lo": _SEQ_MIN, "hi": _SEQ_MAX},
    )


async def delete_all_for_source(src_key: str) -> None:
    """Range-delete every generation's blocks + parse headers for a source.

    Called from ``Source.delete()`` BEFORE the record delete (the DB
    source_delete event is only a slow-path safety net — 2.x ``DELETE ... WHERE``
    ignores secondary indexes; db-design §2.4)."""
    headers = await list_parse_headers(src_key)
    for header in headers:
        await delete_generation(src_key, header.gen)
    sid = RecordID("source", src_key)
    await repo_query(
        f"DELETE {PARSE_TABLE} WHERE source = $sid;",
        {"sid": sid},
    )


async def sweep_orphan_generations(src_key: str, keep_gen: int) -> List[int]:
    """Remove every generation except ``keep_gen`` (its blocks + header).

    Startup / post-flip hygiene (db-design §4 step 9): clears orphaned
    'building' generations and superseded old gens, keeping only the current
    ready generation. Returns the list of generations swept.
    """
    headers = await list_parse_headers(src_key)
    swept: List[int] = []
    for header in headers:
        if header.gen == keep_gen:
            continue
        await delete_generation(src_key, header.gen)
        await repo_query(
            f"DELETE {PARSE_TABLE}:[$k, $g];",
            {"k": src_key, "g": header.gen},
        )
        swept.append(header.gen)
    return swept
