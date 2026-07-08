"""Chunk A2 — block domain + parser-contract tests.

Two layers:
  * pure-python units for parsers.base.finalize() and blocks_to_markdown()
    (no DB — deterministic),
  * one live-DB round trip of the composite-id repo helpers in domain.blocks
    (insert → header fetch → page fetch → window → delete_generation) on a
    THROWAWAY src_key, cleaned up in teardown.
"""

import pytest
import pytest_asyncio
from surrealdb import RecordID

from open_notebook.domain import blocks
from open_notebook.domain.blocks import (
    BLOCK_TABLE,
    PARSE_TABLE,
    block_rid,
    parse_rid,
)
from open_notebook.parsers.base import (
    BBox,
    BlockType,
    ParsedBlock,
    ParseResult,
    blocks_to_markdown,
    finalize,
)

# --------------------------------------------------------------------------- #
# BBox validation
# --------------------------------------------------------------------------- #


def test_bbox_valid():
    b = BBox(l=0.1, t=0.2, r=0.8, b=0.9)
    assert b.as_list() == [0.1, 0.2, 0.8, 0.9]


@pytest.mark.parametrize(
    "kw",
    [
        dict(l=0.8, t=0.1, r=0.2, b=0.9),  # l >= r
        dict(l=0.1, t=0.9, r=0.8, b=0.2),  # t >= b
        dict(l=-0.1, t=0.1, r=0.8, b=0.9),  # l < 0
        dict(l=0.1, t=0.1, r=1.2, b=0.9),  # r > 1
    ],
)
def test_bbox_invalid(kw):
    with pytest.raises(ValueError):
        BBox(**kw)


# --------------------------------------------------------------------------- #
# finalize()
# --------------------------------------------------------------------------- #


def _pb(seq, page, type_, **kw):
    return ParsedBlock(seq=seq, page=page, type=type_, **kw)


def test_finalize_reindex_and_page_monotonic_sort():
    # Deliberately out of order across pages + a sparse seq.
    result = ParseResult(
        parser_name="t",
        parser_version="1",
        page_count=2,
        blocks=[
            _pb(50, 2, BlockType.paragraph, text="p2"),
            _pb(10, 1, BlockType.paragraph, text="p1a"),
            _pb(20, 1, BlockType.paragraph, text="p1b"),
        ],
    )
    fin = finalize(result)
    # contiguous seq 0..N-1 in page-monotonic order
    assert [b.seq for b in fin.blocks] == [0, 1, 2]
    assert [b.page for b in fin.blocks] == [1, 1, 2]
    assert [b.text for b in fin.blocks] == ["p1a", "p1b", "p2"]


def test_finalize_parent_seq_remap_and_validation():
    result = ParseResult(
        parser_name="t",
        parser_version="1",
        page_count=1,
        blocks=[
            _pb(5, 1, BlockType.figure, text="fig"),
            _pb(9, 1, BlockType.caption, text="cap", parent_seq=5),  # valid parent
            _pb(12, 1, BlockType.paragraph, text="p", parent_seq=99),  # dangling
        ],
    )
    fin = finalize(result)
    by_text = {b.text: b for b in fin.blocks}
    # figure reindexed to 0, caption's parent remapped 5 -> 0
    assert by_text["fig"].seq == 0
    assert by_text["cap"].parent_seq == 0
    # dangling parent dropped
    assert by_text["p"].parent_seq is None


def test_finalize_subtree_end_and_section_path():
    result = ParseResult(
        parser_name="t",
        parser_version="1",
        page_count=1,
        blocks=[
            _pb(0, 1, BlockType.heading, text="Ch 1", level=1),
            _pb(1, 1, BlockType.heading, text="Sec 1.1", level=2),
            _pb(2, 1, BlockType.paragraph, text="body"),
            _pb(3, 1, BlockType.heading, text="Ch 2", level=1),
            _pb(4, 1, BlockType.paragraph, text="tail"),
        ],
    )
    fin = finalize(result)
    b = fin.blocks
    # Ch 1 (seq 0) closes just before Ch 2 (seq 3) -> subtree_end 2
    assert b[0].subtree_end == 2
    # Sec 1.1 (seq 1) closed by Ch 2 as well -> subtree_end 2
    assert b[1].subtree_end == 2
    # Ch 2 (seq 3) runs to the last block -> subtree_end 4
    assert b[3].subtree_end == 4
    # section_path breadcrumbs
    assert b[0].section_path == []  # heading excludes itself
    assert b[1].section_path == ["Ch 1"]
    assert b[2].section_path == ["Ch 1", "Sec 1.1"]  # deepest body
    assert b[4].section_path == ["Ch 2"]
    # section_index rebuilt for headings only
    assert [s["title"] for s in fin.section_index] == ["Ch 1", "Sec 1.1", "Ch 2"]


def test_finalize_page_index():
    result = ParseResult(
        parser_name="t",
        parser_version="1",
        page_count=3,
        blocks=[
            _pb(0, 1, BlockType.paragraph, text="a"),
            _pb(1, 1, BlockType.paragraph, text="b"),
            _pb(2, 3, BlockType.paragraph, text="c"),  # page 2 empty
        ],
    )
    fin = finalize(result)
    # page 1 -> seq [0,1]; page 2 empty -> inverted [0,-1]; page 3 -> [2,2]
    assert fin.page_index == [[0, 1], [0, -1], [2, 2]]


# --------------------------------------------------------------------------- #
# blocks_to_markdown()
# --------------------------------------------------------------------------- #


def test_md_equation_and_raw_fallback():
    md = blocks_to_markdown(
        [
            _pb(0, 1, BlockType.equation, latex="E=mc^2"),
            _pb(1, 1, BlockType.equation, text="a+b", latex=None),
        ]
    )
    assert "$$\nE=mc^2\n$$" in md
    assert "a+b" in md  # raw-text fallback when no latex


def test_md_figure_block_uri_with_caption_alt():
    md = blocks_to_markdown([_pb(7, 4, BlockType.figure, text="A cat")])
    assert md == "![A cat](block://7)"


def test_md_figure_default_alt_without_text():
    md = blocks_to_markdown([_pb(7, 4, BlockType.figure)])
    assert md == "![Figure (p.4)](block://7)"


def test_md_heading_depth_clamped_at_six():
    md = blocks_to_markdown([_pb(0, 1, BlockType.heading, text="Deep", level=9)])
    assert md == "###### Deep"


def test_md_headers_and_footers_skipped():
    md = blocks_to_markdown(
        [
            _pb(0, 1, BlockType.page_header, text="running head"),
            _pb(1, 1, BlockType.paragraph, text="real body"),
            _pb(2, 1, BlockType.page_footer, text="page 1"),
        ]
    )
    assert md == "real body"


def test_md_list_caption_code_blank_line_separation():
    md = blocks_to_markdown(
        [
            _pb(0, 1, BlockType.list_item, text="one"),
            _pb(1, 1, BlockType.caption, text="fig caption"),
            _pb(2, 1, BlockType.code, text="print(1)"),
        ]
    )
    assert md == "- one\n\n*fig caption*\n\n```\nprint(1)\n```"


def test_md_accepts_dicts():
    md = blocks_to_markdown([{"type": "paragraph", "text": "hi", "seq": 0, "page": 1}])
    assert md == "hi"


# --------------------------------------------------------------------------- #
# block_rid / parse_rid
# --------------------------------------------------------------------------- #


def test_block_rid_shape():
    rid = block_rid("abc", 2, 41)
    assert isinstance(rid, RecordID)
    assert str(rid).startswith(f"{BLOCK_TABLE}:")
    assert "abc" in str(rid) and "41" in str(rid)


def test_parse_rid_shape():
    rid = parse_rid("abc", 2)
    assert isinstance(rid, RecordID)
    assert str(rid).startswith(f"{PARSE_TABLE}:")


# --------------------------------------------------------------------------- #
# Live-DB round trip (throwaway src_key)
# --------------------------------------------------------------------------- #

_SK = "zz_blocks_a2_test"
_GEN = 1


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_live():
    """Ensure no leftovers before/after the live-DB test."""
    from open_notebook.database.repository import repo_query

    async def _wipe():
        await blocks.delete_generation(_SK, _GEN)
        await repo_query(
            f"DELETE {PARSE_TABLE}:[$k, $g];", {"k": _SK, "g": _GEN}
        )

    await _wipe()
    yield
    await _wipe()


@pytest.mark.asyncio
async def test_live_insert_fetch_window_delete():
    from open_notebook.database.repository import repo_query

    source_ref = RecordID("source", _SK)

    # Seed a parse header with a page_index we can drive get_page_blocks with.
    await repo_query(
        f"CREATE {PARSE_TABLE}:[$k, $g] SET source = $src, gen = $g, "
        "parser_name = 't', parser_version = '1', status = 'ready', "
        "page_index = $pi, page_count = 2, block_count = 5;",
        {
            "k": _SK,
            "g": _GEN,
            "src": source_ref,
            "pi": [[0, 2], [3, 4]],  # page 1 -> seq 0..2, page 2 -> seq 3..4
        },
    )

    # Build block records with EXPLICIT composite RecordIDs.
    records = []
    for seq in range(5):
        page = 1 if seq <= 2 else 2
        records.append(
            {
                "id": block_rid(_SK, _GEN, seq),
                "source": source_ref,
                "gen": _GEN,
                "seq": seq,
                "page": page,
                "type": "paragraph",
                "text": f"block-{seq}",
            }
        )
    inserted = await blocks.bulk_insert_blocks(records, batch_size=2)
    assert inserted == 5

    # Re-insert is idempotent (ignore_duplicates) — no dupes, no error.
    again = await blocks.bulk_insert_blocks(records)
    assert again == 0

    # Parse header round trip.
    header = await blocks.get_parse_header(_SK, _GEN)
    assert header is not None
    assert header.gen == _GEN
    assert header.page_index == [[0, 2], [3, 4]]
    assert header.rid == parse_rid(_SK, _GEN)

    # list_parse_headers finds it.
    headers = await blocks.list_parse_headers(_SK)
    assert [h.gen for h in headers] == [_GEN]

    # Page overlay fetch (page 1 -> seqs 0,1,2), text omitted by default.
    page1 = await blocks.get_page_blocks(_SK, _GEN, 1, header.page_index)
    assert [r["seq"] for r in page1] == [0, 1, 2]
    assert "text" not in page1[0]  # overlay projection excludes text

    # include_text=True selects everything.
    page2 = await blocks.get_page_blocks(_SK, _GEN, 2, header.page_index, include_text=True)
    assert [r["seq"] for r in page2] == [3, 4]
    assert page2[0]["text"] == "block-3"

    # Point get.
    b = await blocks.get_block(_SK, _GEN, 3)
    assert b is not None and b.seq == 3 and b.text == "block-3"
    assert b.rid == block_rid(_SK, _GEN, 3)

    # Window around seq 2, radius 3 -> clamps lo at 0, returns 0..5 (5 blocks).
    win = await blocks.get_window(_SK, _GEN, 2, radius=3)
    assert [r["seq"] for r in win] == [0, 1, 2, 3, 4]

    # Range fetch.
    rng = await blocks.get_range(_SK, _GEN, 1, 3)
    assert [r["seq"] for r in rng] == [1, 2, 3]

    # delete_generation clears the whole band.
    await blocks.delete_generation(_SK, _GEN)
    remaining = await blocks.get_range(_SK, _GEN, 0, 10)
    assert remaining == []
    # header still present (delete_generation only touches blocks)
    assert await blocks.get_parse_header(_SK, _GEN) is not None
