"""Pure geometry + quote-match core for block anchoring (db-design §2.3, §10).

This module is the SHARED, DB-free primitive that both directions of annotation
anchoring reuse:

* **PDF-born** (Track D1, ``block_anchor.resolve_anchor``): a client sends
  highlight rects + the selected quote; the server fetches the page's blocks and
  calls :func:`anchor_match` to resolve the block RANGE + char offsets.
* **Re-anchor** (Track B5): after a re-parse, existing annotations are matched
  against the new generation's blocks via this SAME function (bbox∩rect + quote
  containment / ``quote_hash``) — B5 reuses this file verbatim, it does not
  recreate it.

Per **Decision #13** the result is a multi-block RANGE
``(block_seq, block_end_seq, anchor_start, anchor_end)``:

* single-block highlight → ``block_seq == block_end_seq``, offsets are char
  positions of the quote within that block's text;
* multi-block selection (rects cover several blocks) → the geometric span
  ``first_candidate..last_candidate`` with offsets ``None`` — there is no
  sub-glyph precision across a block boundary because ``char_boxes`` were
  intentionally dropped (db-design §2.3);
* atomic block (``figure``/``table``/``equation``) → offsets ``None``.

Everything here is a pure function of its arguments (no I/O, no DB), so it is
deterministic and unit-testable on synthetic blocks.

Coordinate contract:
* block ``bbox`` = ``[l, t, r, b]`` normalized ``0..1``, top-left origin, y-down
  (db-design §2.1);
* rect = the ``@react-pdf-viewer/highlight`` ``HighlightArea`` shape —
  ``pageIndex`` (0-based) + ``left/top/width/height`` as **percentages 0..100**
  of the page box (api/models.py ``AnnotationRect``). Same origin, so a rect
  intersects a block once its percentages are divided by 100.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Block types that carry no meaningful character stream to offset into — a
# highlight over one of these anchors to the WHOLE block (offsets None).
ATOMIC_TYPES = frozenset({"figure", "table", "equation"})


@dataclass
class AnchorMatch:
    """A resolved block RANGE (Decision #13). ``anchor_start``/``anchor_end`` are
    char offsets within ``block_seq``/``block_end_seq``'s text respectively, or
    ``None`` for a geometric span / atomic block."""

    block_seq: int
    block_end_seq: int
    anchor_start: Optional[int]
    anchor_end: Optional[int]


# --------------------------------------------------------------------------- #
# Quote normalization / hashing (shared with B5's re-anchor by quote_hash).
# --------------------------------------------------------------------------- #


def normalize_quote(quote: Optional[str]) -> str:
    """Whitespace-collapsed, case-folded form used for matching + hashing."""
    if not quote:
        return ""
    return " ".join(quote.split()).casefold()


def quote_hash(quote: Optional[str]) -> Optional[str]:
    """Stable sha256 of the normalized quote (``None`` for an empty quote).

    Used as a re-anchor key: the same selected text hashes identically across
    parse generations regardless of surrounding-whitespace/case differences."""
    nq = normalize_quote(quote)
    if not nq:
        return None
    return hashlib.sha256(nq.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Geometry.
# --------------------------------------------------------------------------- #


def _rect_fraction(rect: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """``HighlightArea`` percentages → ``(l, t, r, b)`` fractions 0..1."""
    try:
        left = float(rect["left"]) / 100.0
        top = float(rect["top"]) / 100.0
        right = left + float(rect["width"]) / 100.0
        bottom = top + float(rect["height"]) / 100.0
    except (KeyError, TypeError, ValueError):
        return None
    return (left, top, right, bottom)


def _boxes_intersect(
    bbox: Sequence[float], rect: Tuple[float, float, float, float]
) -> bool:
    """Axis-aligned overlap test; touching edges do NOT count as overlap."""
    bl, bt, br, bb = bbox[0], bbox[1], bbox[2], bbox[3]
    rl, rt, rr, rb = rect
    if br <= rl or rr <= bl:
        return False
    if bb <= rt or rb <= bt:
        return False
    return True


def _candidates(
    blocks: List[Dict[str, Any]], rects: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Blocks whose bbox intersects ANY rect, in seq order.

    Rects are page-aligned to blocks (``block.page == rect.pageIndex + 1``) so a
    multi-page selection never bleeds one page's rects onto another page's
    blocks."""
    rect_fracs: List[Tuple[Optional[int], Tuple[float, float, float, float]]] = []
    for rect in rects:
        frac = _rect_fraction(rect)
        if frac is None:
            continue
        page_index = rect.get("pageIndex")
        rect_fracs.append((page_index, frac))

    hits: List[Dict[str, Any]] = []
    for block in blocks:
        bbox = block.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        block_page = block.get("page")
        for page_index, frac in rect_fracs:
            if (
                block_page is not None
                and page_index is not None
                and page_index + 1 != block_page
            ):
                continue
            if _boxes_intersect(bbox, frac):
                hits.append(block)
                break
    hits.sort(key=lambda b: b.get("seq", 0))
    return hits


# --------------------------------------------------------------------------- #
# Quote → char offsets within one block's text.
# --------------------------------------------------------------------------- #


def find_offsets(
    text: Optional[str], quote: Optional[str]
) -> Tuple[Optional[int], Optional[int]]:
    """Locate ``quote`` inside ``text``; return ``(start, end)`` or ``(None, None)``.

    Tries, in order: exact substring, case-insensitive substring, then a
    whitespace-tolerant regex (runs of whitespace in the quote match ``\\s+`` in
    the text) so a PDF selection whose line-breaks differ from the block text
    still resolves. Offsets index the RAW ``text`` so they stay usable for
    rendering."""
    if not text or not quote:
        return None, None
    idx = text.find(quote)
    if idx != -1:
        return idx, idx + len(quote)
    lowered = text.casefold()
    idx = lowered.find(quote.casefold())
    if idx != -1:
        return idx, idx + len(quote)
    tokens = quote.split()
    if not tokens:
        return None, None
    pattern = r"\s+".join(re.escape(tok) for tok in tokens)
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return m.start(), m.end()
    return None, None


def _is_atomic(block: Dict[str, Any]) -> bool:
    return str(block.get("type")) in ATOMIC_TYPES


# --------------------------------------------------------------------------- #
# The core.
# --------------------------------------------------------------------------- #


def anchor_match(
    blocks: List[Dict[str, Any]],
    rects: List[Dict[str, Any]],
    quote: Optional[str],
) -> Optional[AnchorMatch]:
    """Resolve a highlight to a block RANGE (Decision #13), or ``None``.

    ``blocks`` are the candidate page's blocks WITH text (each a dict carrying at
    least ``seq``, ``type``, ``bbox``, ``page``, ``text``); ``rects`` are the
    ``HighlightArea`` dicts; ``quote`` is the selected text (may be ``None``).

    Strategy:
      1. candidates = blocks whose bbox ∩ any rect (page-aligned);
      2. if a candidate's text CONTAINS the quote → single-block anchor with
         char offsets (atomic block → offsets ``None``);
      3. otherwise the geometric span of the candidates
         ``(first.seq..last.seq)`` with offsets ``None`` (covers multi-block
         selections; no cross-boundary sub-glyph precision).
    Returns ``None`` when no block intersects the selection.
    """
    candidates = _candidates(blocks, rects)
    if not candidates:
        return None

    if quote and quote.strip():
        for block in candidates:
            start, end = find_offsets(block.get("text"), quote)
            if start is not None:
                seq = block.get("seq", 0)
                if _is_atomic(block):
                    return AnchorMatch(seq, seq, None, None)
                return AnchorMatch(seq, seq, start, end)

    first = candidates[0].get("seq", 0)
    last = candidates[-1].get("seq", 0)
    return AnchorMatch(first, last, None, None)
