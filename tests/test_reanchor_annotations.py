"""Chunk B5 — re-anchor job + old-generation cleanup unit tests.

DB-free: ``reanchor_annotations`` / ``_supersede_old_generations`` only touch
``SourceAnnotation.get_for_source``, the ``blocks`` read/cleanup helpers, and
``repo_update`` — all monkeypatched here. The geometry+quote core
(``anchor_match``) is exercised for real (it is a pure function), so these tests
cover the B5 wiring, not the D1 core (that has its own suite).
"""

from types import SimpleNamespace

import pytest

from commands import block_commands as bc
from open_notebook.utils.anchor_match import quote_hash

# --------------------------------------------------------------------------- #
# Synthetic page-1 blocks (mirror test_block_anchor): a paragraph near the top,
# a figure in the middle, a paragraph near the bottom — vertically stacked.
# --------------------------------------------------------------------------- #


def _block(seq, type_, bbox, text=None, page=1):
    return {"seq": seq, "type": type_, "page": page, "bbox": bbox, "text": text}


PARA_TOP = _block(0, "paragraph", [0.1, 0.10, 0.9, 0.20], "The quick brown fox jumps.")
FIGURE = _block(1, "figure", [0.1, 0.30, 0.9, 0.55], "Figure 1: a resting cat")
PARA_BOT = _block(2, "paragraph", [0.1, 0.65, 0.9, 0.75], "Lazy dogs sleep all day.")
PAGE_BLOCKS = [PARA_TOP, FIGURE, PARA_BOT]


def _rect(top_pct, height_pct, left_pct=10.0, width_pct=80.0, page_index=0):
    return {
        "pageIndex": page_index,
        "left": left_pct,
        "top": top_pct,
        "width": width_pct,
        "height": height_pct,
    }


def _annotation(ann_id, rect=None, quote=None, quote_hash=None, **anchor):
    """A SourceAnnotation-shaped stand-in (only the fields B5 reads/writes)."""
    return SimpleNamespace(
        id=ann_id,
        rect=rect or [],
        quote=quote,
        quote_hash=quote_hash,
        block_seq=anchor.get("block_seq"),
        block_end_seq=anchor.get("block_end_seq"),
        anchor_start=anchor.get("anchor_start"),
        anchor_end=anchor.get("anchor_end"),
        anchor_gen=anchor.get("anchor_gen"),
    )


def _patch(monkeypatch, annotations, page_blocks=PAGE_BLOCKS, page_index=[[0, 2]]):
    """Stub get_for_source / get_parse_header / get_page_blocks / repo_update.

    Returns the list of ``(record_id, update_dict)`` repo_update calls.
    """
    updates: list = []

    async def _fake_get_for_source(source_id):
        return list(annotations)

    async def _fake_header(src_key, gen):
        return None if page_index is None else SimpleNamespace(page_index=page_index)

    async def _fake_page_blocks(src_key, gen, page, pidx, include_text=False):
        assert include_text is True
        return page_blocks

    async def _fake_repo_update(table, record_id, data):
        updates.append((str(record_id), dict(data)))
        return []

    monkeypatch.setattr(bc.SourceAnnotation, "get_for_source", _fake_get_for_source)
    monkeypatch.setattr(bc.blocks, "get_parse_header", _fake_header)
    monkeypatch.setattr(bc.blocks, "get_page_blocks", _fake_page_blocks)
    monkeypatch.setattr(bc, "repo_update", _fake_repo_update)
    return updates


def _source():
    return SimpleNamespace(id="source:abc", parse_generation=7)


# --------------------------------------------------------------------------- #
# reanchor_annotations
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reanchor_hit_sets_block_seq_and_gen(monkeypatch):
    ann = _annotation("source_annotation:1", rect=[_rect(10.0, 10.0)], quote="quick brown")
    updates = _patch(monkeypatch, [ann])

    n = await bc.reanchor_annotations(_source(), 7)

    assert n == 1
    assert len(updates) == 1
    rid, data = updates[0]
    assert rid == "source_annotation:1"
    assert data["block_seq"] == 0 and data["block_end_seq"] == 0
    assert (data["anchor_start"], data["anchor_end"]) == (4, 15)
    assert data["anchor_gen"] == 7
    # legacy backfill: quote_hash computed since the annotation had none.
    assert data["quote_hash"] == quote_hash("quick brown")


@pytest.mark.asyncio
async def test_reanchor_multi_block_range(monkeypatch):
    # A tall selection spanning the top AND bottom paragraph, no quote →
    # geometric span 0..2 (Decision #13 RANGE), offsets None.
    ann = _annotation("source_annotation:2", rect=[_rect(10.0, 70.0)], quote=None)
    updates = _patch(monkeypatch, [ann])

    n = await bc.reanchor_annotations(_source(), 7)

    assert n == 1
    _, data = updates[0]
    assert data["block_seq"] == 0 and data["block_end_seq"] == 2
    assert data["anchor_start"] is None and data["anchor_end"] is None
    assert data["anchor_gen"] == 7


@pytest.mark.asyncio
async def test_reanchor_atomic_figure_offsets_none(monkeypatch):
    ann = _annotation("source_annotation:3", rect=[_rect(32.0, 20.0)], quote="resting cat")
    updates = _patch(monkeypatch, [ann])

    n = await bc.reanchor_annotations(_source(), 7)

    assert n == 1
    _, data = updates[0]
    assert data["block_seq"] == 1 and data["block_end_seq"] == 1
    assert data["anchor_start"] is None and data["anchor_end"] is None
    assert data["anchor_gen"] == 7


@pytest.mark.asyncio
async def test_reanchor_miss_leaves_fields_unchanged_and_usable(monkeypatch):
    # Rect in an empty region → no candidate block; the annotation already has a
    # quote_hash so there is nothing to persist → repo_update is never called and
    # its previous anchor (block_seq=5, anchor_gen=1) survives untouched.
    ann = _annotation(
        "source_annotation:4",
        rect=[_rect(90.0, 5.0)],
        quote="quick brown",
        quote_hash=quote_hash("quick brown"),
        block_seq=5,
        block_end_seq=5,
        anchor_gen=1,
    )
    updates = _patch(monkeypatch, [ann])

    n = await bc.reanchor_annotations(_source(), 7)

    assert n == 0
    assert updates == []  # no write → prior anchor + gen mismatch (stale) preserved


@pytest.mark.asyncio
async def test_reanchor_legacy_backfill_computes_quote_hash(monkeypatch):
    # A pre-block-era annotation: has a quote, no quote_hash, and no rects (can't
    # geometrically anchor) → only quote_hash is backfilled, no anchor fields.
    ann = _annotation("source_annotation:5", rect=[], quote="Some old highlight")
    updates = _patch(monkeypatch, [ann])

    n = await bc.reanchor_annotations(_source(), 7)

    assert n == 0
    assert len(updates) == 1
    _, data = updates[0]
    assert data == {"quote_hash": quote_hash("Some old highlight")}
    assert "block_seq" not in data and "anchor_gen" not in data


@pytest.mark.asyncio
async def test_reanchor_no_annotations_returns_zero(monkeypatch):
    updates = _patch(monkeypatch, [])
    assert await bc.reanchor_annotations(_source(), 7) == 0
    assert updates == []


@pytest.mark.asyncio
async def test_reanchor_no_header_skips_geometry_but_backfills(monkeypatch):
    # No parse header for the gen → no page_index → geometry skipped, but a legacy
    # quote_hash backfill still fires (independent of blocks).
    ann = _annotation("source_annotation:6", rect=[_rect(10.0, 10.0)], quote="quick brown")
    updates = _patch(monkeypatch, [ann], page_index=None)

    n = await bc.reanchor_annotations(_source(), 7)

    assert n == 0
    assert len(updates) == 1
    _, data = updates[0]
    assert data == {"quote_hash": quote_hash("quick brown")}


# --------------------------------------------------------------------------- #
# _supersede_old_generations
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_supersede_old_generations(monkeypatch):
    headers = [
        SimpleNamespace(gen=1, status="superseded"),
        SimpleNamespace(gen=2, status="ready"),  # the previously-live gen
        SimpleNamespace(gen=3, status="failed"),  # blocks already dropped → skip
        SimpleNamespace(gen=4, status="building"),  # orphan → skip (swept on entry)
        SimpleNamespace(gen=5, status="ready"),  # keep_gen (the new live gen)
    ]
    deleted: list = []
    marked: list = []

    async def _fake_list(src_key):
        return headers

    async def _fake_delete(src_key, gen):
        deleted.append(gen)

    async def _fake_repo_update(table, record_id, data):
        marked.append((str(record_id), data.get("status")))
        return []

    monkeypatch.setattr(bc.blocks, "list_parse_headers", _fake_list)
    monkeypatch.setattr(bc.blocks, "delete_generation", _fake_delete)
    monkeypatch.setattr(bc, "repo_update", _fake_repo_update)

    swept = await bc._supersede_old_generations("abc", keep_gen=5)

    assert swept == [1, 2]  # only non-keep ready/superseded gens
    assert deleted == [1, 2]
    assert all(status == "superseded" for _, status in marked)
    # Both marks target the old gens' parse headers (format-agnostic check).
    assert {rid for rid, _ in marked} == {
        str(bc.parse_rid("abc", 1)),
        str(bc.parse_rid("abc", 2)),
    }


@pytest.mark.asyncio
async def test_supersede_first_parse_no_old_gens(monkeypatch):
    async def _fake_list(src_key):
        return [SimpleNamespace(gen=1, status="ready")]

    async def _boom(*a, **k):
        raise AssertionError("no old gen to delete on a first-ever parse")

    monkeypatch.setattr(bc.blocks, "list_parse_headers", _fake_list)
    monkeypatch.setattr(bc.blocks, "delete_generation", _boom)

    assert await bc._supersede_old_generations("abc", keep_gen=1) == []
