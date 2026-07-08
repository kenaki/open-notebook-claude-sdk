"""Figure/table crop rasterization for the PDF block substrate (db-design §4
step 3, Decision #6).

Figure and table blocks get a servable PNG crop so the reader/chat surfaces can
render them (the ``block://<seq>`` markdown ref resolves to
``/api/sources/{id}/blocks/{seq}/image``). Each crop is rasterized from the
source PDF at **200 DPI** with **pypdfium2** (a transitive dep of Docling) and
written to::

    {UPLOADS_FOLDER}/blocks/{src_key}/{gen}/{seq}.png

The block's ``image_ref`` is set to the path RELATIVE to ``UPLOADS_FOLDER``
(``blocks/{src_key}/{gen}/{seq}.png``) so serving/cleanup stay data-folder
relative like every other asset.

Crop strategy (db-design Decision #6): prefer Docling's own captured
``PictureItem`` image when the adapter attached one to the block; otherwise
rasterize the block's normalized bbox region from the PDF. The current Docling
adapter does not carry an in-memory image on ``ParsedBlock`` (the frozen parser
contract has no image field), so in practice every crop is rasterized from the
bbox — the Docling-image branch is kept as a graceful fast-path for any parser
that does attach one.

Robustness: a per-block failure (missing bbox, degenerate crop, render error)
is warned via loguru and leaves ``image_ref=None`` — it NEVER aborts the parse.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional, Tuple

from loguru import logger

from open_notebook import config

# Rasterization DPI (Decision #6). PDF user space is 72 DPI, so the pypdfium2
# render scale is DPI/72.
CROP_DPI = 200
_RENDER_SCALE = CROP_DPI / 72.0

# Subdirectory under UPLOADS_FOLDER that holds every source's block crops.
BLOCKS_SUBDIR = "blocks"


# --------------------------------------------------------------------------- #
# Path helpers (also used by the domain crop-cleanup hook).
# --------------------------------------------------------------------------- #


def crop_dir(src_key: str, gen: Optional[int] = None) -> Path:
    """Absolute crop directory for a source (all gens) or one generation.

    ``{UPLOADS_FOLDER}/blocks/{src_key}`` when ``gen`` is None, else
    ``.../{src_key}/{gen}``. Reads ``config.UPLOADS_FOLDER`` dynamically so tests
    can redirect the data folder.
    """
    base = Path(config.UPLOADS_FOLDER) / BLOCKS_SUBDIR / str(src_key)
    return base if gen is None else base / str(gen)


def _relative_ref(src_key: str, gen: int, seq: int) -> str:
    """``image_ref`` value — path relative to ``UPLOADS_FOLDER`` (posix)."""
    return f"{BLOCKS_SUBDIR}/{src_key}/{gen}/{seq}.png"


def remove_crop_dir(src_key: str, gen: Optional[int] = None) -> None:
    """``shutil.rmtree`` the crop dir for a source (or one gen), ignore-missing.

    Called from the domain generation-cleanup hooks so deleting a generation (or
    a whole source) also reclaims its rasterized crops.
    """
    import shutil

    target = crop_dir(src_key, gen)
    try:
        shutil.rmtree(target, ignore_errors=True)
    except Exception as exc:  # pragma: no cover - rmtree already swallows most
        logger.debug(f"remove_crop_dir: skip {target}: {exc!r}")


# --------------------------------------------------------------------------- #
# bbox extraction (tolerant of BBox / list / dict / None).
# --------------------------------------------------------------------------- #


def _bbox_tuple(block: Any) -> Optional[Tuple[float, float, float, float]]:
    """Normalized ``(l, t, r, b)`` for a block, or None when absent/malformed."""
    bbox = block.get("bbox") if isinstance(block, dict) else getattr(block, "bbox", None)
    if bbox is None:
        return None
    try:
        if isinstance(bbox, (list, tuple)):
            l, t, r, b = (float(v) for v in bbox[:4])
        elif isinstance(bbox, dict):
            l, t, r, b = (float(bbox[k]) for k in ("l", "t", "r", "b"))
        else:  # BBox pydantic model (or anything with l/t/r/b attrs)
            l, t, r, b = (
                float(bbox.l),
                float(bbox.t),
                float(bbox.r),
                float(bbox.b),
            )
    except Exception:
        return None
    return (l, t, r, b)


def _docling_image(block: Any):
    """Return a Docling-captured PIL image attached to the block, or None.

    The frozen ``ParsedBlock`` contract has no image field, so this only fires
    for parsers that stash one on a private attribute; it degrades to None
    (→ bbox rasterization) otherwise.
    """
    if isinstance(block, dict):
        return block.get("_pil_image") or block.get("pil_image")
    return getattr(block, "_pil_image", None) or getattr(block, "pil_image", None)


# --------------------------------------------------------------------------- #
# Public entry point.
# --------------------------------------------------------------------------- #


def extract_block_images(
    pdf_path: Any,
    blocks: List[Any],
    src_key: str,
    gen: int,
) -> None:
    """Rasterize figure/table crops for ``blocks`` and set each ``image_ref``.

    Mutates every ``figure``/``table`` block in place: on success ``image_ref``
    becomes the path relative to ``UPLOADS_FOLDER``; on any per-block failure it
    is set to ``None`` (warned, never raised). Blocks that are neither figures
    nor tables are left untouched. The PDF is opened once and each page rendered
    lazily and cached, so a page with many figures pays a single render.
    """
    targets = [b for b in blocks if _is_croppable(b)]
    if not targets:
        return

    out_dir = crop_dir(src_key, gen)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as exc:
        logger.warning(
            f"extract_block_images: cannot create crop dir {out_dir}: {exc!r}; "
            f"skipping {len(targets)} crops"
        )
        for block in targets:
            _set_ref(block, None)
        return

    try:
        import pypdfium2 as pdfium
    except Exception as exc:  # pragma: no cover - pypdfium2 ships with docling
        logger.warning(
            f"extract_block_images: pypdfium2 unavailable ({exc!r}); "
            f"skipping {len(targets)} crops"
        )
        for block in targets:
            _set_ref(block, None)
        return

    pdf = None
    page_cache: dict = {}
    written = 0
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
        n_pages = len(pdf)
        for block in targets:
            seq = _field(block, "seq")
            try:
                ref = _render_one(
                    pdf, page_cache, n_pages, block, out_dir, src_key, gen, seq
                )
                _set_ref(block, ref)
                if ref is not None:
                    written += 1
            except Exception as exc:
                logger.warning(
                    f"extract_block_images: crop failed for seq={seq} "
                    f"({src_key}/{gen}): {exc!r}"
                )
                _set_ref(block, None)
    except Exception as exc:
        # Whole-document failure (e.g. unreadable PDF): every target gets no ref.
        logger.warning(
            f"extract_block_images: cannot open {pdf_path} ({exc!r}); "
            f"skipping {len(targets)} crops"
        )
        for block in targets:
            _set_ref(block, None)
    finally:
        if pdf is not None:
            try:
                pdf.close()
            except Exception:  # pragma: no cover
                pass

    logger.info(
        f"extract_block_images: wrote {written}/{len(targets)} crops for "
        f"{src_key} gen {gen} → {out_dir}"
    )


# --------------------------------------------------------------------------- #
# Internals.
# --------------------------------------------------------------------------- #


def _is_croppable(block: Any) -> bool:
    btype = _field(block, "type")
    btype = getattr(btype, "value", btype)
    return str(btype) in ("figure", "table")


def _field(block: Any, name: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def _set_ref(block: Any, ref: Optional[str]) -> None:
    if isinstance(block, dict):
        block["image_ref"] = ref
    else:
        block.image_ref = ref


def _render_one(
    pdf,
    page_cache: dict,
    n_pages: int,
    block: Any,
    out_dir: Path,
    src_key: str,
    gen: int,
    seq: int,
) -> Optional[str]:
    """Write one crop PNG; return its relative ref or None (no bbox / no image)."""
    out_path = out_dir / f"{seq}.png"

    # 1. Prefer a Docling-captured PIL image when a parser attached one.
    dimg = _docling_image(block)
    if dimg is not None:
        dimg.save(str(out_path), "PNG")
        return _relative_ref(src_key, gen, seq)

    # 2. Rasterize the bbox region from the PDF page at 200 DPI.
    bbox = _bbox_tuple(block)
    if bbox is None:
        return None  # no geometry to crop — leave image_ref None (not an error)

    page = _field(block, "page")
    try:
        page_idx = int(page) - 1  # blocks store 1-based physical page
    except Exception:
        return None
    if page_idx < 0 or page_idx >= n_pages:
        return None

    pil_page = page_cache.get(page_idx)
    if pil_page is None:
        bmp = pdf[page_idx].render(scale=_RENDER_SCALE)
        pil_page = bmp.to_pil()
        page_cache[page_idx] = pil_page

    width_px, height_px = pil_page.size
    l, t, r, b = bbox
    left = int(round(l * width_px))
    top = int(round(t * height_px))
    right = int(round(r * width_px))
    bottom = int(round(b * height_px))
    # Clamp to the page and guarantee a non-empty crop box.
    left = max(0, min(left, width_px - 1))
    top = max(0, min(top, height_px - 1))
    right = max(left + 1, min(right, width_px))
    bottom = max(top + 1, min(bottom, height_px))

    crop = pil_page.crop((left, top, right, bottom))
    crop.save(str(out_path), "PNG")
    return _relative_ref(src_key, gen, seq)
