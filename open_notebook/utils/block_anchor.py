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
from open_notebook.utils.anchor_match import anchor_match, quote_hash


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
