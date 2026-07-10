"""Tests for the Docling block adapter (Chunk B1).

The parse-based tests run Docling on a small committed fixture PDF
(``tests/fixtures/blocks_sample.pdf``, 3 pages, born-digital). Docling loads
layout models on first use, so the parse is slow — it runs once via a
module-scoped fixture and every assertion reads that single result.

Pure-function tests (``page_map_from_blocks``, ``parser_version``) need no PDF.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from open_notebook.parsers.base import (
    BlockType,
    FinalizedParse,
    ParseResult,
    finalize,
)
from open_notebook.parsers.docling_parser import (
    DoclingBlockParser,
    _rebuild_code_lines,
    _reflows_to,
    page_map_from_blocks,
    parser_version,
)

FIXTURE = Path(__file__).parent / "fixtures" / "blocks_sample.pdf"


def test_fixture_exists():
    assert FIXTURE.is_file(), f"missing fixture PDF: {FIXTURE}"


@pytest.fixture(scope="module")
def parsed() -> ParseResult:
    return DoclingBlockParser().parse(FIXTURE)


@pytest.fixture(scope="module")
def finalized(parsed: ParseResult) -> FinalizedParse:
    return finalize(parsed)


# --------------------------------------------------------------------------- #
# ParseResult shape
# --------------------------------------------------------------------------- #


def test_parse_result_metadata(parsed: ParseResult):
    assert parsed.parser_name == "docling"
    assert parsed.parser_version.startswith("docling-")
    assert "+tables+formula" in parsed.parser_version
    assert parsed.page_count == 3
    assert len(parsed.pages) == 3
    assert parsed.capabilities >= {"text", "bbox", "headings", "figures"}


def test_typed_blocks_emitted(parsed: ParseResult):
    """The whole point of B1: Docling items become TYPED blocks, not flat text."""
    assert parsed.blocks, "no blocks emitted"
    kinds = {b.type for b in parsed.blocks}
    # Every emitted type is a valid BlockType (StrEnum) — no stray strings.
    for b in parsed.blocks:
        assert isinstance(b.type, BlockType)
    # The born-digital fixture must yield at least headings and paragraphs.
    assert BlockType.heading in kinds
    assert BlockType.paragraph in kinds


def test_heading_levels(parsed: ParseResult):
    headings = [b for b in parsed.blocks if b.type == BlockType.heading]
    assert headings, "expected at least one heading block"
    for h in headings:
        assert isinstance(h.level, int) and h.level >= 1
        assert h.text and h.text.strip()


def test_bboxes_normalized_unit_square(parsed: ParseResult):
    """Every bbox the adapter emits is normalized, top-left, in [0,1]."""
    seen = 0
    for b in parsed.blocks:
        if b.bbox is None:
            continue  # malformed prov is allowed to drop geometry, keep block
        seen += 1
        l, t, r, b_ = b.bbox.l, b.bbox.t, b.bbox.r, b.bbox.b
        assert 0.0 <= l < r <= 1.0, f"seq={b.seq} bad x: {l},{r}"
        assert 0.0 <= t < b_ <= 1.0, f"seq={b.seq} bad y: {t},{b_}"
    assert seen > 0, "expected at least one block with a bbox"


def test_pages_within_document(parsed: ParseResult):
    for b in parsed.blocks:
        assert 1 <= b.page <= parsed.page_count


# --------------------------------------------------------------------------- #
# finalize() integration — page monotonicity + derived structures
# --------------------------------------------------------------------------- #


def test_page_monotonic_after_finalize(finalized: FinalizedParse):
    """Blocks come out in reading order: page never decreases as seq grows,
    and seq is contiguous 0..N-1."""
    seqs = [b.seq for b in finalized.blocks]
    assert seqs == list(range(len(finalized.blocks)))
    pages = [b.page for b in finalized.blocks]
    assert pages == sorted(pages), "page order not monotonic after finalize"


def test_page_index_aligned(finalized: FinalizedParse):
    """page_index is dense, indexed by page-1, covering every page."""
    assert len(finalized.page_index) == finalized.page_count
    for page in range(1, finalized.page_count + 1):
        lo, hi = finalized.page_index[page - 1]
        page_seqs = [b.seq for b in finalized.blocks if b.page == page]
        if page_seqs:
            assert [lo, hi] == [min(page_seqs), max(page_seqs)]
        else:
            assert [lo, hi] == [0, -1]  # empty-page sentinel


def test_section_index_from_headings(finalized: FinalizedParse):
    heading_seqs = {b.seq for b in finalized.blocks if b.type == BlockType.heading}
    idx_seqs = {s["seq"] for s in finalized.section_index}
    assert idx_seqs == heading_seqs
    for s in finalized.section_index:
        assert s["level"] >= 1
        assert isinstance(s["subtree_end"], int)


# --------------------------------------------------------------------------- #
# page_map compatibility (Decision #9) + version string (pure, no PDF)
# --------------------------------------------------------------------------- #


def test_page_map_compat_shape(finalized: FinalizedParse):
    pm = page_map_from_blocks(finalized.blocks)
    assert isinstance(pm, list) and pm, "page_map empty"
    for entry in pm:
        assert set(entry) == {"text", "page_no"}
        assert isinstance(entry["text"], str) and entry["text"]
        assert isinstance(entry["page_no"], int) and entry["page_no"] >= 1
    # Monotonic-ish: page numbers never exceed the document page count.
    assert max(e["page_no"] for e in pm) <= finalized.page_count


def test_page_map_from_blocks_pure():
    """Pure unit — dicts and objects, equations contribute latex, no-text skipped."""
    blocks = [
        {"type": "paragraph", "text": "hello", "page": 1},
        {"type": "equation", "text": None, "latex": "E=mc^2", "page": 2},
        {"type": "figure", "text": None, "page": 2},  # no text/latex -> skipped
    ]
    pm = page_map_from_blocks(blocks)
    assert pm == [
        {"text": "hello", "page_no": 1},
        {"text": "E=mc^2", "page_no": 2},
    ]


def test_parser_version_is_config_derived():
    v = parser_version()
    assert v.startswith("docling-")
    assert v.endswith("+tables+formula+codelines")
    # Deterministic for a given install.
    assert parser_version() == v


# --------------------------------------------------------------------------- #
# Code block re-lineation (pure geometry — no Docling, no PDF)
# --------------------------------------------------------------------------- #

PAGE_H = 100.0
CHAR_W = 6.0


class _Rect:
    def __init__(self, x0, y, x1):
        self.r_x0 = x0
        self.r_x1 = x1
        self.r_y0 = y
        self.r_y2 = y


class _Cell:
    def __init__(self, x0, y, text):
        self.text = text
        self.rect = _Rect(x0, y, x0 + CHAR_W * len(text))


class _ParsedPage:
    def __init__(self, cells):
        self.textline_cells = cells


class _Page:
    def __init__(self, cells):
        self.parsed_page = _ParsedPage(cells)


class _BBox:
    """A BOTTOMLEFT-origin box covering the whole synthetic page."""

    l = 0.0  # noqa: E741 - mirrors Docling's attribute name
    r = 500.0
    t = PAGE_H  # top edge, measured up from the bottom
    b = 0.0


def _rebuild(cells):
    return _rebuild_code_lines(_Page(cells), _BBox(), PAGE_H)


def test_rebuild_splits_lines_by_y_centre():
    # `def f():` on one line, an indented `return 1` on the next.
    cells = [_Cell(0.0, 10.0, "def f():"), _Cell(4 * CHAR_W, 22.0, "return 1")]
    assert _rebuild(cells) == "def f():\n    return 1"


def test_rebuild_converts_x_gaps_to_spaces():
    # Two fragments on one line separated by a three-character gap.
    cells = [
        _Cell(0.0, 10.0, "a = 1"),
        _Cell(5 * CHAR_W + 3 * CHAR_W, 10.0, "# set"),
    ]
    assert _rebuild(cells) == "a = 1   # set"


def test_rebuild_orders_fragments_within_a_line_by_x():
    # Cell order is arbitrary; output order must follow geometry, not input.
    cells = [_Cell(2 * CHAR_W, 10.0, "world"), _Cell(0.0, 10.0, "hello ")]
    assert _rebuild(cells) == "hello world"


def test_rebuild_treats_cells_within_tolerance_as_one_line():
    # A 2pt baseline jitter (subscript, mixed font) is the same visual line.
    cells = [_Cell(0.0, 10.0, "value"), _Cell(5 * CHAR_W, 12.0, "= 3")]
    assert _rebuild(cells) == "value= 3"


def test_rebuild_returns_none_without_cells():
    assert _rebuild([]) is None


def test_reflows_to_accepts_whitespace_only_differences():
    assert _reflows_to("def f():\n    return 1", "def f(): return 1")


def test_reflows_to_rejects_changed_characters():
    # The guard that keeps a bad rebuild (or a VLM-style re-transcription that
    # invents or drops text) from replacing Docling's own characters.
    assert not _reflows_to("def f():\n    return 2", "def f(): return 1")
    assert not _reflows_to("extra def f(): return 1", "def f(): return 1")


def test_code_text_falls_back_when_rebuild_is_not_a_reflow():
    # Cells that don't match Docling's text (e.g. wrong page) must not win.
    parser = DoclingBlockParser()

    class _Prov:
        page_no = 1
        bbox = _BBox()

    cells = [_Cell(0.0, 10.0, "totally"), _Cell(0.0, 22.0, "different")]
    out = parser._code_text(
        object(), _Prov(), {1: _Page(cells)}, PAGE_H, "def f(): return 1"
    )
    assert out == "def f(): return 1"


def test_code_text_falls_back_without_a_backend_page():
    parser = DoclingBlockParser()

    class _Prov:
        page_no = 7
        bbox = _BBox()

    out = parser._code_text(object(), _Prov(), {}, PAGE_H, "def f(): return 1")
    assert out == "def f(): return 1"


def test_code_text_uses_the_rebuild_when_it_reflows():
    parser = DoclingBlockParser()

    class _Prov:
        page_no = 1
        bbox = _BBox()

    cells = [_Cell(0.0, 10.0, "def f():"), _Cell(4 * CHAR_W, 22.0, "return 1")]
    out = parser._code_text(
        object(), _Prov(), {1: _Page(cells)}, PAGE_H, "def f(): return 1"
    )
    assert out == "def f():\n    return 1"
