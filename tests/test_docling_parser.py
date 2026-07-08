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
    assert v.endswith("+tables+formula")
    # Deterministic for a given install.
    assert parser_version() == v
