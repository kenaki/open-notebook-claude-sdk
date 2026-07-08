"""Chunk B3 — figure/table crop rasterization tests.

Exercises ``open_notebook.utils.block_images.extract_block_images`` on synthetic
blocks against the committed 3-page fixture PDF (from B1), plus the domain
crop-cleanup hook. No live DB: the ``delete_generation`` test stubs
``repo_query`` and only asserts the filesystem side effect.

Every test redirects ``config.UPLOADS_FOLDER`` to a tmp dir so nothing touches
the real data folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from open_notebook import config
from open_notebook.parsers.base import BBox, BlockType, ParsedBlock
from open_notebook.utils import block_images

FIXTURE = Path(__file__).parent / "fixtures" / "blocks_sample.pdf"


@pytest.fixture(autouse=True)
def _tmp_uploads(tmp_path, monkeypatch):
    """Redirect UPLOADS_FOLDER to a throwaway dir for every test."""
    monkeypatch.setattr(config, "UPLOADS_FOLDER", str(tmp_path))
    return tmp_path


def _fig(seq: int, page: int = 1, bbox=(0.1, 0.1, 0.6, 0.5)) -> ParsedBlock:
    l, t, r, b = bbox
    return ParsedBlock(
        seq=seq,
        page=page,
        type=BlockType.figure,
        bbox=BBox(l=l, t=t, r=r, b=b),
    )


def _table(seq: int, page: int = 1, bbox=(0.2, 0.55, 0.8, 0.9)) -> ParsedBlock:
    l, t, r, b = bbox
    return ParsedBlock(
        seq=seq,
        page=page,
        type=BlockType.table,
        text="| a | b |\n|---|---|\n| 1 | 2 |",
        bbox=BBox(l=l, t=t, r=r, b=b),
    )


def test_fixture_exists():
    assert FIXTURE.is_file(), f"missing fixture PDF: {FIXTURE}"


def test_writes_valid_png_and_sets_relative_ref(_tmp_uploads):
    from PIL import Image

    src_key, gen = "srcKEY", 3
    fig = _fig(seq=5)
    tbl = _table(seq=9)
    blocks = [fig, tbl]

    block_images.extract_block_images(FIXTURE, blocks, src_key, gen)

    # image_ref is set RELATIVE to UPLOADS_FOLDER (posix, no leading slash).
    assert fig.image_ref == f"blocks/{src_key}/{gen}/5.png"
    assert tbl.image_ref == f"blocks/{src_key}/{gen}/9.png"

    for block in blocks:
        abs_path = Path(_tmp_uploads) / block.image_ref
        assert abs_path.is_file(), f"crop not written: {abs_path}"
        # Files open as valid, non-empty PNGs.
        with Image.open(abs_path) as img:
            assert img.format == "PNG"
            assert img.width > 0 and img.height > 0


def test_crop_dir_layout(_tmp_uploads):
    src_key, gen = "abc", 1
    block_images.extract_block_images(FIXTURE, [_fig(seq=0)], src_key, gen)
    expected_dir = Path(_tmp_uploads) / "blocks" / src_key / str(gen)
    assert expected_dir.is_dir()
    assert (expected_dir / "0.png").is_file()


def test_bbox_less_block_yields_none_and_does_not_raise(_tmp_uploads):
    # A figure with no bbox cannot be cropped → image_ref stays None, no raise.
    fig_no_bbox = ParsedBlock(seq=2, page=1, type=BlockType.figure, bbox=None)
    block_images.extract_block_images(FIXTURE, [fig_no_bbox], "k", 1)
    assert fig_no_bbox.image_ref is None
    # Nothing written for it.
    assert not (Path(_tmp_uploads) / "blocks" / "k" / "1" / "2.png").exists()


def test_out_of_range_page_yields_none(_tmp_uploads):
    # Fixture has 3 pages; page 99 is out of range → None, no raise.
    fig = _fig(seq=1, page=99)
    block_images.extract_block_images(FIXTURE, [fig], "k", 1)
    assert fig.image_ref is None


def test_non_figure_table_blocks_untouched(_tmp_uploads):
    para = ParsedBlock(
        seq=0,
        page=1,
        type=BlockType.paragraph,
        text="hello",
        bbox=BBox(l=0.1, t=0.1, r=0.9, b=0.2),
    )
    heading = ParsedBlock(seq=1, page=1, type=BlockType.heading, text="Title", level=1)
    block_images.extract_block_images(FIXTURE, [para, heading], "k", 1)
    assert para.image_ref is None
    assert heading.image_ref is None
    # No crop dir is created when there are no croppable targets.
    assert not (Path(_tmp_uploads) / "blocks").exists()


def test_mixed_bbox_and_bbox_less_isolated(_tmp_uploads):
    good = _fig(seq=1)
    bad = ParsedBlock(seq=2, page=1, type=BlockType.figure, bbox=None)
    block_images.extract_block_images(FIXTURE, [good, bad, _table(seq=3)], "k", 7)
    assert good.image_ref == "blocks/k/7/1.png"
    assert bad.image_ref is None
    # good + table crops present, no 2.png.
    d = Path(_tmp_uploads) / "blocks" / "k" / "7"
    assert (d / "1.png").is_file()
    assert (d / "3.png").is_file()
    assert not (d / "2.png").exists()


def test_unreadable_pdf_marks_all_none(_tmp_uploads, tmp_path):
    bogus = tmp_path / "not_a.pdf"
    bogus.write_bytes(b"%PDF-1.4 not really")
    fig = _fig(seq=1)
    # Must not raise even though the PDF can't be opened.
    block_images.extract_block_images(bogus, [fig], "k", 1)
    assert fig.image_ref is None


def test_prefers_docling_attached_image(_tmp_uploads):
    from PIL import Image

    # A block carrying an in-memory PIL image is written directly, bypassing
    # pdfium rasterization (Decision #6 fast-path). Uses a dict block since the
    # frozen ParsedBlock contract has no image field.
    fig = {
        "seq": 4,
        "page": 1,
        "type": "figure",
        "bbox": None,  # no bbox, yet still cropped via the attached image
        "_pil_image": Image.new("RGB", (12, 8), "red"),
    }
    block_images.extract_block_images(FIXTURE, [fig], "k", 2)
    assert fig["image_ref"] == "blocks/k/2/4.png"
    with Image.open(Path(_tmp_uploads) / fig["image_ref"]) as img:
        assert img.size == (12, 8)


@pytest.mark.asyncio
async def test_delete_generation_removes_crop_dir(_tmp_uploads, monkeypatch):
    from open_notebook.domain import blocks as blocks_domain

    # Stub the DB round trip — we only assert the filesystem cleanup.
    async def _noop_query(*args, **kwargs):
        return []

    monkeypatch.setattr(blocks_domain, "repo_query", _noop_query)

    src_key, gen = "delkey", 4
    gen_dir = block_images.crop_dir(src_key, gen)
    gen_dir.mkdir(parents=True)
    (gen_dir / "0.png").write_bytes(b"x")
    assert gen_dir.is_dir()

    await blocks_domain.delete_generation(src_key, gen)
    assert not gen_dir.exists()


@pytest.mark.asyncio
async def test_delete_all_for_source_removes_crop_tree(_tmp_uploads, monkeypatch):
    from open_notebook.domain import blocks as blocks_domain

    async def _noop_query(*args, **kwargs):
        return []

    async def _no_headers(_src_key):
        return []

    monkeypatch.setattr(blocks_domain, "repo_query", _noop_query)
    monkeypatch.setattr(blocks_domain, "list_parse_headers", _no_headers)

    src_key = "srcdel"
    src_dir = block_images.crop_dir(src_key)
    (src_dir / "1").mkdir(parents=True)
    (src_dir / "1" / "0.png").write_bytes(b"x")
    assert src_dir.is_dir()

    await blocks_domain.delete_all_for_source(src_key)
    assert not src_dir.exists()


def test_remove_crop_dir_ignores_missing(_tmp_uploads):
    # No such dir — must be a silent no-op.
    block_images.remove_crop_dir("nope", 1)
    block_images.remove_crop_dir("nope")
