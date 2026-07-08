"""Chunk D1 — anchor capture backend tests.

Two layers, both DB-free:
  * pure-python units for the shared ``anchor_match`` geometry+quote core
    (bbox∩rect candidates, quote offsets, atomic whole-block, geometric span),
  * ``block_anchor.resolve_anchor`` with the two ``blocks`` DB helpers
    monkeypatched (happy path, unparsed source → None, missing header → None).

No live DB — ``resolve_anchor``'s only I/O is ``blocks.get_parse_header`` /
``blocks.get_page_blocks``, which are stubbed here.
"""

from types import SimpleNamespace

import pytest

from open_notebook.utils import block_anchor
from open_notebook.utils.anchor_match import (
    AnchorMatch,
    anchor_match,
    find_offsets,
    normalize_quote,
    quote_hash,
)

# --------------------------------------------------------------------------- #
# Synthetic blocks — page 1, non-overlapping vertical bboxes (0..1 fractions).
# --------------------------------------------------------------------------- #


def _block(seq, type_, bbox, text=None, page=1):
    return {"seq": seq, "type": type_, "page": page, "bbox": bbox, "text": text}


# One paragraph near the top, a figure in the middle, a paragraph near the
# bottom — vertically stacked so a rect band selects exactly one of them.
PARA_TOP = _block(0, "paragraph", [0.1, 0.10, 0.9, 0.20], "The quick brown fox jumps.")
FIGURE = _block(1, "figure", [0.1, 0.30, 0.9, 0.55], "Figure 1: a resting cat")
PARA_BOT = _block(2, "paragraph", [0.1, 0.65, 0.9, 0.75], "Lazy dogs sleep all day.")
PAGE_BLOCKS = [PARA_TOP, FIGURE, PARA_BOT]


def _rect(top_pct, height_pct, left_pct=10.0, width_pct=80.0, page_index=0):
    """A HighlightArea (percentages 0..100) over a horizontal band of the page."""
    return {
        "pageIndex": page_index,
        "left": left_pct,
        "top": top_pct,
        "width": width_pct,
        "height": height_pct,
    }


# --------------------------------------------------------------------------- #
# normalize_quote / quote_hash
# --------------------------------------------------------------------------- #


def test_normalize_quote_collapses_whitespace_and_case():
    assert normalize_quote("  The   Quick\nBROWN  ") == "the quick brown"
    assert normalize_quote(None) == ""
    assert normalize_quote("   ") == ""


def test_quote_hash_stable_and_normalized():
    assert quote_hash(None) is None
    assert quote_hash("   ") is None
    # Same text, different surrounding whitespace/case → identical hash.
    assert quote_hash("The quick brown") == quote_hash("  the   QUICK brown ")
    assert quote_hash("a") != quote_hash("b")


# --------------------------------------------------------------------------- #
# find_offsets
# --------------------------------------------------------------------------- #


def test_find_offsets_exact():
    assert find_offsets("hello world", "world") == (6, 11)


def test_find_offsets_case_insensitive():
    assert find_offsets("Hello World", "world") == (6, 11)


def test_find_offsets_whitespace_tolerant():
    # A PDF selection whose line-break differs from the block text.
    s, e = find_offsets("quick brown fox", "brown\nfox")
    assert (s, e) == (6, 15)


def test_find_offsets_miss():
    assert find_offsets("hello", "absent") == (None, None)
    assert find_offsets(None, "x") == (None, None)


# --------------------------------------------------------------------------- #
# anchor_match — hit / multi-rect / figure whole-block / span / none
# --------------------------------------------------------------------------- #


def test_anchor_match_single_block_hit_with_offsets():
    rects = [_rect(top_pct=10.0, height_pct=10.0)]  # band over PARA_TOP
    m = anchor_match(PAGE_BLOCKS, rects, "quick brown")
    assert m == AnchorMatch(0, 0, 4, 15)  # "quick brown" at chars 4..15


def test_anchor_match_multi_rect_same_block():
    # Two line-rects of a multi-line selection, both over PARA_TOP → one block.
    rects = [_rect(top_pct=10.0, height_pct=5.0), _rect(top_pct=15.0, height_pct=5.0)]
    m = anchor_match(PAGE_BLOCKS, rects, "brown fox")
    assert m is not None
    assert (m.block_seq, m.block_end_seq) == (0, 0)
    assert m.anchor_start is not None and m.anchor_end is not None


def test_anchor_match_figure_whole_block_offsets_none():
    # Selection over the figure; even though its caption text contains the quote,
    # an atomic block anchors WHOLE-block with offsets None.
    rects = [_rect(top_pct=32.0, height_pct=20.0)]
    m = anchor_match(PAGE_BLOCKS, rects, "resting cat")
    assert m == AnchorMatch(1, 1, None, None)


def test_anchor_match_geometric_span_multi_block_no_quote():
    # A tall selection covering the top paragraph AND the bottom paragraph, with
    # no quote → geometric span first..last, offsets None (Decision #13 range).
    rects = [_rect(top_pct=10.0, height_pct=70.0)]
    m = anchor_match(PAGE_BLOCKS, rects, None)
    assert m == AnchorMatch(0, 2, None, None)


def test_anchor_match_no_candidate_returns_none():
    # A rect in a region no block occupies.
    rects = [_rect(top_pct=90.0, height_pct=5.0)]
    assert anchor_match(PAGE_BLOCKS, rects, "quick") is None


def test_anchor_match_page_alignment_ignores_other_page_rects():
    # Rect on page 2 must not match a page-1 block even if geometry overlaps.
    rects = [_rect(top_pct=10.0, height_pct=10.0, page_index=1)]
    assert anchor_match(PAGE_BLOCKS, rects, "quick brown") is None


# --------------------------------------------------------------------------- #
# resolve_anchor — DB helpers stubbed
# --------------------------------------------------------------------------- #


def _patch_blocks(monkeypatch, header, page_blocks):
    async def _fake_header(src_key, gen):
        return header

    async def _fake_page_blocks(src_key, gen, page, page_index, include_text=False):
        assert include_text is True  # resolve_anchor must request text
        return page_blocks

    monkeypatch.setattr(block_anchor.blocks, "get_parse_header", _fake_header)
    monkeypatch.setattr(block_anchor.blocks, "get_page_blocks", _fake_page_blocks)


@pytest.mark.asyncio
async def test_resolve_anchor_unparsed_source_returns_none(monkeypatch):
    called = {"header": False}

    async def _boom(*a, **k):
        called["header"] = True
        raise AssertionError("should not touch the DB for an unparsed source")

    monkeypatch.setattr(block_anchor.blocks, "get_parse_header", _boom)
    src = SimpleNamespace(id="source:abc", parse_generation=None)
    assert await block_anchor.resolve_anchor(src, [_rect(10.0, 10.0)], "quick") is None
    assert called["header"] is False


@pytest.mark.asyncio
async def test_resolve_anchor_no_rects_returns_none(monkeypatch):
    src = SimpleNamespace(id="source:abc", parse_generation=1)
    assert await block_anchor.resolve_anchor(src, [], "quick") is None


@pytest.mark.asyncio
async def test_resolve_anchor_missing_header_returns_none(monkeypatch):
    _patch_blocks(monkeypatch, header=None, page_blocks=[])
    src = SimpleNamespace(id="source:abc", parse_generation=2)
    assert await block_anchor.resolve_anchor(src, [_rect(10.0, 10.0)], "quick") is None


@pytest.mark.asyncio
async def test_resolve_anchor_happy_path(monkeypatch):
    header = SimpleNamespace(page_index=[[0, 2]])
    _patch_blocks(monkeypatch, header=header, page_blocks=PAGE_BLOCKS)
    src = SimpleNamespace(id="source:abc", parse_generation=3)

    result = await block_anchor.resolve_anchor(
        src, [_rect(top_pct=10.0, height_pct=10.0)], "quick brown"
    )
    assert result is not None
    assert result.block_seq == 0 and result.block_end_seq == 0
    assert (result.anchor_start, result.anchor_end) == (4, 15)
    assert result.anchor_gen == 3
    assert result.quote_hash == quote_hash("quick brown")


@pytest.mark.asyncio
async def test_resolve_anchor_figure_offsets_none(monkeypatch):
    header = SimpleNamespace(page_index=[[0, 2]])
    _patch_blocks(monkeypatch, header=header, page_blocks=PAGE_BLOCKS)
    src = SimpleNamespace(id="source:abc", parse_generation=3)

    result = await block_anchor.resolve_anchor(
        src, [_rect(top_pct=32.0, height_pct=20.0)], "resting cat"
    )
    assert result is not None
    assert (result.block_seq, result.block_end_seq) == (1, 1)
    assert result.anchor_start is None and result.anchor_end is None
    assert result.anchor_gen == 3


@pytest.mark.asyncio
async def test_resolve_anchor_no_page_blocks_returns_none(monkeypatch):
    header = SimpleNamespace(page_index=[[0, 2]])
    _patch_blocks(monkeypatch, header=header, page_blocks=[])
    src = SimpleNamespace(id="source:abc", parse_generation=3)
    assert await block_anchor.resolve_anchor(src, [_rect(10.0, 10.0)], "quick") is None


# --------------------------------------------------------------------------- #
# derive_reader_anchor — reader-born (Track D7): block range -> derived rect.
# blocks.get_range is stubbed (SELECT * raw dicts).
# --------------------------------------------------------------------------- #


def _patch_get_range(monkeypatch, rows):
    async def _fake_get_range(src_key, gen, lo, hi):
        return [r for r in rows if lo <= r["seq"] <= hi]

    monkeypatch.setattr(block_anchor.blocks, "get_range", _fake_get_range)


@pytest.mark.asyncio
async def test_derive_reader_anchor_single_text_block(monkeypatch):
    _patch_get_range(monkeypatch, PAGE_BLOCKS)
    src = SimpleNamespace(id="source:abc", parse_generation=4)

    result = await block_anchor.derive_reader_anchor(
        src, block_seq=0, block_end_seq=0, anchor_start=4, anchor_end=15, quote="quick brown"
    )
    # Offsets preserved for a single text block.
    assert (result.block_seq, result.block_end_seq) == (0, 0)
    assert (result.anchor_start, result.anchor_end) == (4, 15)
    assert result.anchor_gen == 4
    assert result.quote_hash == quote_hash("quick brown")
    # One rect derived from the block bbox [0.1, 0.10, 0.9, 0.20] -> percentages.
    assert result.page == 1
    assert len(result.rect) == 1
    rect = result.rect[0]
    assert rect["pageIndex"] == 0
    assert rect["left"] == pytest.approx(10.0)
    assert rect["top"] == pytest.approx(10.0)
    assert rect["width"] == pytest.approx(80.0)
    assert rect["height"] == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_derive_reader_anchor_atomic_block_offsets_none(monkeypatch):
    _patch_get_range(monkeypatch, PAGE_BLOCKS)
    src = SimpleNamespace(id="source:abc", parse_generation=4)

    result = await block_anchor.derive_reader_anchor(
        src, block_seq=1, block_end_seq=1, anchor_start=0, anchor_end=5, quote="resting cat"
    )
    # Atomic figure -> offsets dropped even though client sent them.
    assert (result.block_seq, result.block_end_seq) == (1, 1)
    assert result.anchor_start is None and result.anchor_end is None
    assert len(result.rect) == 1


@pytest.mark.asyncio
async def test_derive_reader_anchor_multi_block_span_offsets_none(monkeypatch):
    _patch_get_range(monkeypatch, PAGE_BLOCKS)
    src = SimpleNamespace(id="source:abc", parse_generation=4)

    result = await block_anchor.derive_reader_anchor(
        src, block_seq=0, block_end_seq=2, anchor_start=1, anchor_end=3, quote=None
    )
    assert (result.block_seq, result.block_end_seq) == (0, 2)
    assert result.anchor_start is None and result.anchor_end is None
    # One rect per positioned block in the range.
    assert len(result.rect) == 3


@pytest.mark.asyncio
async def test_derive_reader_anchor_out_of_bounds_offsets_dropped(monkeypatch):
    _patch_get_range(monkeypatch, PAGE_BLOCKS)
    src = SimpleNamespace(id="source:abc", parse_generation=4)

    result = await block_anchor.derive_reader_anchor(
        src, block_seq=0, block_end_seq=0, anchor_start=0, anchor_end=9999, quote="x"
    )
    assert result.anchor_start is None and result.anchor_end is None


@pytest.mark.asyncio
async def test_derive_reader_anchor_unparsed_source_409(monkeypatch):
    src = SimpleNamespace(id="source:abc", parse_generation=None)
    with pytest.raises(block_anchor.ReaderAnchorError) as exc:
        await block_anchor.derive_reader_anchor(
            src, block_seq=0, block_end_seq=0, anchor_start=None, anchor_end=None, quote="x"
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_derive_reader_anchor_missing_range_404(monkeypatch):
    # Range refers to seqs absent from the current generation (stale/wrong-gen).
    _patch_get_range(monkeypatch, PAGE_BLOCKS)
    src = SimpleNamespace(id="source:abc", parse_generation=4)
    with pytest.raises(block_anchor.ReaderAnchorError) as exc:
        await block_anchor.derive_reader_anchor(
            src, block_seq=50, block_end_seq=51, anchor_start=None, anchor_end=None, quote="x"
        )
    assert exc.value.status_code == 404
