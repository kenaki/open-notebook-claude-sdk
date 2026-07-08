"""PDF-born annotation anchoring (Track D1, db-design §2.3 / §10).

Resolves a freshly-created highlight (rects + selected quote) to the block
substrate at create time: fetch the selected page's blocks WITH text and hand
them to the pure :func:`anchor_match` core (bbox∩rect + quote containment) to
get a block RANGE + char offsets. The DB-free geometry/quote logic lives in
``anchor_match`` so Track B5's re-anchor job reuses it verbatim; this module is
just the DB round trip around it.

Staleness is never stored — it is derived downstream from ``anchor_gen`` vs the
source's current ``parse_generation`` (db-design §2.3). An un-parsed source
(``parse_generation is None``) yields ``None`` here and the annotation stays a
legacy rect/quote-only record forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from open_notebook.domain import blocks
from open_notebook.utils.anchor_match import ATOMIC_TYPES, anchor_match, quote_hash


@dataclass
class AnchorResult:
    """The resolved anchor persisted onto a ``SourceAnnotation`` (Decision #13).

    ``block_seq``/``block_end_seq`` is the block RANGE the highlight covers
    (equal for a single-block highlight); ``anchor_start``/``anchor_end`` are the
    char offsets within those blocks (``None`` for a geometric span or an atomic
    figure/table/equation); ``anchor_gen`` records the generation resolved
    against (staleness = ``anchor_gen != source.parse_generation``);
    ``quote_hash`` is the re-anchor key."""

    block_seq: int
    block_end_seq: int
    anchor_start: Optional[int]
    anchor_end: Optional[int]
    anchor_gen: int
    quote_hash: Optional[str]


def _src_key(source_id: Any) -> str:
    """Bare record key from ``source:<key>`` (mirrors blocks._src_key)."""
    s = str(source_id)
    return s.split(":", 1)[1] if ":" in s else s


async def resolve_anchor(
    source: Any,
    rects: List[Dict[str, Any]],
    quote: Optional[str],
) -> Optional[AnchorResult]:
    """Resolve a highlight to a block anchor, or ``None`` (legacy annotation).

    ``source`` needs only ``.id`` and ``.parse_generation`` (a full ``Source`` or
    a ``get_meta`` projection both work — ``parse_generation`` survives the OMIT).
    ``rects`` are ``HighlightArea`` dicts (``pageIndex`` 0-based +
    ``left/top/width/height`` percentages); ``quote`` is the selected text.

    Returns ``None`` when the source has no parse generation, has no header/blocks
    for the page, or no block intersects the selection — in every such case the
    annotation is stored as a legacy rect/quote-only record.
    """
    if source is None or getattr(source, "parse_generation", None) is None:
        return None
    if not rects:
        return None

    gen = source.parse_generation
    src_key = _src_key(getattr(source, "id", ""))
    if not src_key:
        return None

    # page = 1-based physical page of the first rect (db-design §10).
    try:
        page = int(rects[0]["pageIndex"]) + 1
    except (KeyError, TypeError, ValueError):
        return None

    header = await blocks.get_parse_header(src_key, gen)
    if header is None or not header.page_index:
        return None

    page_blocks = await blocks.get_page_blocks(
        src_key, gen, page, header.page_index, include_text=True
    )
    if not page_blocks:
        return None

    match = anchor_match(page_blocks, rects, quote)
    if match is None:
        return None

    return AnchorResult(
        block_seq=match.block_seq,
        block_end_seq=match.block_end_seq,
        anchor_start=match.anchor_start,
        anchor_end=match.anchor_end,
        anchor_gen=gen,
        quote_hash=quote_hash(quote),
    )


# --------------------------------------------------------------------------- #
# Reader-born anchoring (Track D7, db-design §2.3): the client sends a block
# RANGE + char offsets + quote; the server DERIVES the render rect from the
# blocks' bboxes so the highlight still paints on the PDF tab. The inverse of
# resolve_anchor (which goes rect -> block); this goes block -> rect.
# --------------------------------------------------------------------------- #


class ReaderAnchorError(Exception):
    """A reader-born create couldn't be anchored to the current generation.

    Carries the HTTP status the router should surface: 409 when the source has
    no parsed generation to anchor to, 404 when the block range doesn't exist in
    the current generation (e.g. a stale range from a superseded parse)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class ReaderAnchorResult:
    """A reader-born anchor with the DERIVED render rect + page (db-design §2.3).

    ``rect`` is one ``HighlightArea``-shaped dict per block in the range (bbox
    0..1 → percentages 0..100, ``pageIndex = block.page - 1``); ``page`` is the
    1-based page of the first block; offsets are the char positions within the
    single text block (``None`` for a multi-block span or an atomic block)."""

    page: int
    rect: List[Dict[str, Any]]
    block_seq: int
    block_end_seq: int
    anchor_start: Optional[int]
    anchor_end: Optional[int]
    anchor_gen: int
    quote_hash: Optional[str]


def _bbox_to_rect(bbox: List[float], page: int) -> Dict[str, Any]:
    """One block bbox (``[l, t, r, b]`` 0..1) → a ``HighlightArea`` percentage
    rect (``pageIndex`` 0-based). Inverse of ``anchor_match._rect_fraction``."""
    left, top, right, bottom = bbox[0], bbox[1], bbox[2], bbox[3]
    return {
        "pageIndex": page - 1,
        "left": left * 100.0,
        "top": top * 100.0,
        "width": (right - left) * 100.0,
        "height": (bottom - top) * 100.0,
    }


async def derive_reader_anchor(
    source: Any,
    block_seq: int,
    block_end_seq: int,
    anchor_start: Optional[int],
    anchor_end: Optional[int],
    quote: Optional[str],
) -> ReaderAnchorResult:
    """Resolve a reader-born selection to a persisted anchor + derived rect.

    Validates that ``block_seq..block_end_seq`` exists in the source's CURRENT
    ``parse_generation`` and derives one render rect per block from its bbox.
    Raises :class:`ReaderAnchorError` (409 unparsed / 404 missing range).

    Offsets are kept only for a single, non-atomic text block; a multi-block
    span or an atomic figure/table/equation stores ``None`` (block-granular, no
    sub-glyph precision since ``char_boxes`` were dropped — Q-reader-selection-edge).
    """
    gen = getattr(source, "parse_generation", None)
    if gen is None:
        raise ReaderAnchorError(409, "Source has no parsed generation to anchor to")
    src_key = _src_key(getattr(source, "id", ""))
    if not src_key:
        raise ReaderAnchorError(409, "Source id is missing")

    lo, hi = (block_seq, block_end_seq)
    if lo > hi:
        lo, hi = hi, lo

    rows = await blocks.get_range(src_key, gen, lo, hi)
    seqs = {row.get("seq") for row in rows}
    if not rows or lo not in seqs or hi not in seqs:
        raise ReaderAnchorError(
            404, f"Block range {lo}..{hi} not found in generation {gen}"
        )

    ordered = sorted(rows, key=lambda r: r.get("seq", 0))
    rects: List[Dict[str, Any]] = []
    for row in ordered:
        bbox = row.get("bbox")
        page = row.get("page")
        if bbox and len(bbox) == 4 and page is not None:
            rects.append(_bbox_to_rect(bbox, int(page)))
    if not rects:
        raise ReaderAnchorError(
            404, "Block range has no positioned blocks to derive a rect from"
        )

    page = int(ordered[0].get("page"))

    # Offsets survive only for a single, non-atomic text block; otherwise None.
    start, end = anchor_start, anchor_end
    if lo != hi:
        start = end = None
    else:
        block = ordered[0]
        if str(block.get("type")) in ATOMIC_TYPES:
            start = end = None
        else:
            text = block.get("text") or ""
            if (
                start is None
                or end is None
                or start < 0
                or end > len(text)
                or start > end
            ):
                start = end = None

    return ReaderAnchorResult(
        page=page,
        rect=rects,
        block_seq=lo,
        block_end_seq=hi,
        anchor_start=start,
        anchor_end=end,
        anchor_gen=gen,
        quote_hash=quote_hash(quote),
    )
