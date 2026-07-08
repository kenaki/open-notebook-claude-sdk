"""Docling adapter — first :class:`~open_notebook.parsers.base.BlockParser`.

Docling's typed layout items (``iterate_items()``) are currently discarded by
``graphs/source.py`` (only ``page_map`` — flat ``{text, page_no}`` — survives).
This adapter turns those items into a full :class:`ParseResult`: typed blocks
with normalized top-left bounding boxes, heading levels, table markdown + cell
structure, figure/caption links, and LaTeX equations (Decision #7 — no
server-side KaTeX validation).

Converter config (db-design §5, B1 spec):
- ``do_ocr=False`` — RapidOCR's PyTorch backend crashes on this env
  (``Unsupported configuration: torch.PP-OCRv6.det.small``); born-digital PDFs
  carry a text layer so OCR adds nothing. (Scanned pages → no text; DEF-1
  Nemotron OCR is the deferred fix.)
- ``do_table_structure=True`` — table cell grid → ``table_data``.
- ``do_formula_enrichment=True`` — formula items expose LaTeX in ``.text``.

The config participates in ``parser_version`` (``docling-<ver>+tables+formula``)
so a config change bumps the version and triggers a re-parse generation.

Callers run :func:`~open_notebook.parsers.base.finalize` on the result to fill
contiguous ``seq``, ``subtree_end``, ``section_path``, ``page_index`` and
``section_index``. This module never touches the DB.
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.parsers.base import (
    BBox,
    BlockType,
    PageInfo,
    ParsedBlock,
    ParseResult,
)

PARSER_NAME = "docling"


def _docling_version() -> str:
    try:
        return importlib.metadata.version("docling")
    except Exception:  # pragma: no cover - packaging edge
        return "unknown"


def parser_version() -> str:
    """``docling-<libver>+tables+formula`` — the config-derived version string.

    Any change to the enrichment config here MUST change this string so a
    re-parse produces a new generation (db-design §4/§5)."""
    return f"{PARSER_NAME}-{_docling_version()}+tables+formula"


def _normalized_bbox(prov: Any, page_w: float, page_h: float) -> Optional[BBox]:
    """Docling ``prov[0].bbox`` → normalized top-left ``BBox`` (0..1, y-down).

    Docling boxes are usually BOTTOMLEFT origin; flip to top-left, normalize by
    page size, clamp to [0,1]. Any degenerate / out-of-range box (which the
    strict ``BBox`` validator rejects) yields ``None`` — the block is kept, only
    its geometry is dropped (never silently drop the block like source.py does)."""
    try:
        from docling_core.types.doc.base import CoordOrigin

        bbox = prov.bbox
        origin = getattr(bbox, "coord_origin", None)
        if origin == CoordOrigin.BOTTOMLEFT:
            # Prefer Docling's own converter when present; fall back to a manual
            # flip (top = H - y_top, y grows downward afterwards).
            to_tl = getattr(bbox, "to_top_left_origin", None)
            if callable(to_tl):
                bbox = to_tl(page_h)
                l, t, r, b = bbox.l, bbox.t, bbox.r, bbox.b
            else:
                l, r = bbox.l, bbox.r
                t, b = page_h - bbox.t, page_h - bbox.b
        else:
            l, t, r, b = bbox.l, bbox.t, bbox.r, bbox.b

        if not (page_w and page_h):
            return None

        nl, nr = l / page_w, r / page_w
        nt, nb = t / page_h, b / page_h
        # Order-normalize (a flip can invert t/b) and clamp to the unit square.
        nl, nr = min(nl, nr), max(nl, nr)
        nt, nb = min(nt, nb), max(nt, nb)
        nl, nr = max(0.0, min(1.0, nl)), max(0.0, min(1.0, nr))
        nt, nb = max(0.0, min(1.0, nt)), max(0.0, min(1.0, nb))
        return BBox(l=nl, t=nt, r=nr, b=nb)
    except Exception:
        # Malformed / degenerate provenance — keep the block, drop the geometry.
        return None


class DoclingBlockParser:
    """Turns a born-digital PDF into a typed :class:`ParseResult` via Docling."""

    parser_name = PARSER_NAME

    def __init__(self) -> None:
        self.parser_version = parser_version()

    # -- converter -------------------------------------------------------- #
    def _build_converter(self):
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        opts = PdfPipelineOptions()
        opts.do_ocr = False
        opts.do_table_structure = True
        opts.do_formula_enrichment = True
        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=opts)
            }
        )

    # -- helpers ---------------------------------------------------------- #
    @staticmethod
    def _page_sizes(doc: Any) -> Dict[int, tuple]:
        sizes: Dict[int, tuple] = {}
        pages = getattr(doc, "pages", {}) or {}
        for page_no, page in pages.items():
            size = getattr(page, "size", None)
            if size is not None:
                sizes[int(page_no)] = (
                    float(getattr(size, "width", 0.0) or 0.0),
                    float(getattr(size, "height", 0.0) or 0.0),
                )
        return sizes

    @staticmethod
    def _table_markdown(item: Any, doc: Any) -> Optional[str]:
        try:
            return item.export_to_markdown(doc)
        except TypeError:
            try:
                return item.export_to_markdown()
            except Exception:
                return None
        except Exception:
            return None

    @staticmethod
    def _table_data(item: Any) -> Optional[dict]:
        data = getattr(item, "data", None)
        if data is None:
            return None
        try:
            return data.model_dump(mode="json")
        except Exception:
            try:
                return dict(data)
            except Exception:
                return None

    # -- main ------------------------------------------------------------- #
    def parse(self, pdf_path: Path) -> ParseResult:
        # Lazy imports keep Docling out of the import graph until a PDF arrives
        # (mirrors the existing import guards in graphs/source.py).
        from docling_core.types.doc.document import (
            CodeItem,
            FormulaItem,
            ListItem,
            PictureItem,
            SectionHeaderItem,
            TableItem,
            TextItem,
            TitleItem,
        )
        from docling_core.types.doc import DocItemLabel

        converter = self._build_converter()
        result = converter.convert(str(pdf_path))
        doc = result.document

        page_sizes = self._page_sizes(doc)
        page_count = len(page_sizes) or getattr(doc, "num_pages", lambda: 0)()

        # Pass 1: enumerate items for provisional seq + caption→picture linkage.
        items: List[tuple] = list(doc.iterate_items())
        self_ref_seq: Dict[str, int] = {}
        for i, (item, _level) in enumerate(items):
            ref = getattr(item, "self_ref", None)
            if ref is not None:
                self_ref_seq[ref] = i

        caption_parent: Dict[str, int] = {}  # caption self_ref -> picture seq
        for i, (item, _level) in enumerate(items):
            if isinstance(item, PictureItem):
                for cap in getattr(item, "captions", []) or []:
                    cref = getattr(cap, "cref", None) or getattr(cap, "$ref", None)
                    if cref is not None:
                        caption_parent[cref] = i

        blocks: List[ParsedBlock] = []
        last_page = 1

        for seq, (item, _level) in enumerate(items):
            prov_list = getattr(item, "prov", None) or []
            prov = prov_list[0] if prov_list else None
            page = int(getattr(prov, "page_no", 0) or 0) if prov else 0
            if page <= 0:
                page = last_page  # carry-forward when provenance is missing
            last_page = page

            page_w, page_h = page_sizes.get(page, (0.0, 0.0))
            bbox = _normalized_bbox(prov, page_w, page_h) if prov else None

            btype: Optional[BlockType] = None
            text: Optional[str] = None
            latex: Optional[str] = None
            level: Optional[int] = None
            table_data: Optional[dict] = None
            parent_seq: Optional[int] = None

            # Order matters: the specific subclasses come before generic TextItem
            # (SectionHeader/Title/Formula/Code/List all subclass TextItem).
            if isinstance(item, TableItem):
                btype = BlockType.table
                text = self._table_markdown(item, doc)
                table_data = self._table_data(item)
            elif isinstance(item, PictureItem):
                btype = BlockType.figure
                text = None  # captions become their own `caption` blocks
            elif isinstance(item, FormulaItem):
                btype = BlockType.equation
                latex = (getattr(item, "text", None) or "").strip() or None
            elif isinstance(item, CodeItem):
                btype = BlockType.code
                text = getattr(item, "text", None)
            elif isinstance(item, SectionHeaderItem):
                btype = BlockType.heading
                text = getattr(item, "text", None)
                lvl = getattr(item, "level", None)
                level = int(lvl) if isinstance(lvl, int) and lvl >= 1 else 1
            elif isinstance(item, TitleItem):
                btype = BlockType.heading
                text = getattr(item, "text", None)
                level = 1
            elif isinstance(item, ListItem):
                btype = BlockType.list_item
                text = getattr(item, "text", None)
            elif isinstance(item, TextItem):
                label = getattr(item, "label", None)
                text = getattr(item, "text", None)
                if label == DocItemLabel.FORMULA:
                    btype = BlockType.equation
                    latex = (text or "").strip() or None
                    text = None
                elif label == DocItemLabel.CAPTION:
                    btype = BlockType.caption
                    ref = getattr(item, "self_ref", None)
                    parent_seq = caption_parent.get(ref) if ref else None
                elif label == DocItemLabel.FOOTNOTE:
                    btype = BlockType.footnote
                elif label == DocItemLabel.PAGE_HEADER:
                    btype = BlockType.page_header
                elif label == DocItemLabel.PAGE_FOOTER:
                    btype = BlockType.page_footer
                elif label == DocItemLabel.LIST_ITEM:
                    btype = BlockType.list_item
                elif label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE):
                    btype = BlockType.heading
                    level = 1
                else:
                    btype = BlockType.paragraph
            else:
                # GroupItem / unknown container — no standalone block.
                continue

            # Skip empty non-visual blocks (a figure legitimately has no text).
            if btype not in (BlockType.figure, BlockType.equation) and not (
                text and text.strip()
            ):
                continue
            if btype == BlockType.equation and not latex:
                # Formula enrichment produced nothing usable — keep as paragraph
                # only if there is raw text, else drop.
                raw = getattr(item, "text", None)
                if raw and raw.strip():
                    btype, text, latex = BlockType.paragraph, raw, None
                else:
                    continue

            blocks.append(
                ParsedBlock(
                    seq=seq,
                    page=page,
                    type=btype,
                    text=text,
                    latex=latex,
                    bbox=bbox,
                    parent_seq=parent_seq,
                    level=level,
                    table_data=table_data,
                )
            )

        pages = [
            PageInfo(page=p, width=w, height=h)
            for p, (w, h) in sorted(page_sizes.items())
        ]

        logger.info(
            f"DoclingBlockParser: {len(blocks)} blocks across {page_count} pages "
            f"({self.parser_version})"
        )

        return ParseResult(
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            page_count=page_count,
            pages=pages,
            blocks=blocks,
            capabilities={
                "text",
                "bbox",
                "tables",
                "formulas",
                "headings",
                "figures",
            },
        )


def page_map_from_blocks(blocks: List[Any]) -> List[Dict]:
    """Legacy ``[{text, page_no}]`` page provenance (db-design §7, Decision #9).

    Non-PDF sources and legacy consumers still read ``source.page_map``. One
    entry per text-bearing block (equations contribute their LaTeX) in seq
    order; ``page_no`` is Docling's 1-based physical page."""
    page_map: List[Dict] = []
    for block in blocks:
        if isinstance(block, dict):
            text = block.get("text") or block.get("latex")
            page = block.get("page")
        else:
            text = getattr(block, "text", None) or getattr(block, "latex", None)
            page = getattr(block, "page", None)
        if text and page is not None:
            page_map.append({"text": text, "page_no": int(page)})
    return page_map
