"""Parser abstraction for the PDF block substrate (db-design.md §5).

Pure, DB-free contract shared by every block parser (Docling first). A parser
emits a :class:`ParseResult`; the shared :func:`finalize` post-pass fills in
whatever a weak parser cannot (contiguous ``seq``, ``subtree_end``,
``section_path``, ``page_index``, ``section_index``) so parsers degrade
gracefully instead of breaking the contract.

Also hosts :func:`blocks_to_markdown` — the canonical, deterministic serializer
(Decision #14) that regenerates ``source.full_text`` from a seq-ordered block
list so equations ($$latex$$), figures (``block://`` refs) and tables survive
into every full_text consumer (chat context, search, transformations, content
tab). No DB access anywhere in this module.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, List, Optional, Protocol, Set

from loguru import logger
from pydantic import BaseModel, model_validator


class BlockType(StrEnum):
    """Typed layout roles a parser can emit. Enforced in Pydantic, NOT via a DB
    ASSERT — adding a new type must never require a migration (db-design §2.1)."""

    heading = "heading"
    paragraph = "paragraph"
    list = "list"
    list_item = "list_item"
    code = "code"
    figure = "figure"
    table = "table"
    equation = "equation"
    caption = "caption"
    footnote = "footnote"
    page_header = "page_header"
    page_footer = "page_footer"


class BBox(BaseModel):
    """Normalized bounding box, 0..1, top-left origin, y-down.

    Validated: ``0 <= l < r <= 1`` and ``0 <= t < b <= 1``.
    """

    l: float
    t: float
    r: float
    b: float

    @model_validator(mode="after")
    def _validate_bounds(self) -> "BBox":
        if not (0.0 <= self.l < self.r <= 1.0):
            raise ValueError(
                f"BBox horizontal bounds invalid: 0<=l<r<=1 (l={self.l}, r={self.r})"
            )
        if not (0.0 <= self.t < self.b <= 1.0):
            raise ValueError(
                f"BBox vertical bounds invalid: 0<=t<b<=1 (t={self.t}, b={self.b})"
            )
        return self

    def as_list(self) -> List[float]:
        """[l, t, r, b] — the shape stored in ``document_block.bbox``."""
        return [self.l, self.t, self.r, self.b]


class PageInfo(BaseModel):
    """Per-page geometry captured from the parser."""

    page: int
    width: float
    height: float
    rotation: int = 0


class ParsedBlock(BaseModel):
    """One typed block as emitted by a parser (pre-finalize)."""

    seq: int
    page: int
    type: BlockType
    text: Optional[str] = None
    latex: Optional[str] = None
    image_ref: Optional[str] = None
    bbox: Optional[BBox] = None
    parent_seq: Optional[int] = None
    level: Optional[int] = None
    section_path: List[str] = []
    confidence: Optional[float] = None
    table_data: Optional[dict] = None
    subtree_end: Optional[int] = None


class ParseResult(BaseModel):
    """Everything a parser produces for one PDF (db-design §5, verbatim)."""

    parser_name: str
    parser_version: str
    page_count: int
    pages: List[PageInfo] = []
    blocks: List[ParsedBlock] = []
    capabilities: Set[str] = set()


class FinalizedParse(BaseModel):
    """Output of :func:`finalize` — parser passthrough + the derived structures
    the write path needs (page_index, section_index) with blocks in final
    reading order and contiguous ``seq``."""

    parser_name: str
    parser_version: str
    page_count: int
    pages: List[PageInfo] = []
    capabilities: Set[str] = set()
    blocks: List[ParsedBlock] = []
    page_index: List[List[int]] = []
    section_index: List[dict] = []


class BlockParser(Protocol):
    """The plugin boundary. A parser turns a PDF path into a ParseResult."""

    def parse(self, pdf_path: Path) -> ParseResult: ...


def finalize(result: ParseResult) -> FinalizedParse:
    """Shared post-pass turning a raw ParseResult into a FinalizedParse.

    Steps (db-design §4 step 3):
    1. Page-monotonic re-sort — stable sort by (page, incoming seq) so pages
       come out in reading order.
    2. Contiguous seq reindex — reassign seq 0..N-1 in sorted order and remap
       every ``parent_seq`` through the old→new map.
    3. ``subtree_end`` + ``section_path`` — via a heading-level stack: a heading
       at level L closes every open heading with level >= L (its subtree_end is
       the seq just before this heading); a block's section_path is the chain of
       currently-open heading titles.
    4. ``parent_seq < seq`` validation — a dangling / forward parent is dropped
       to None (with a warning) rather than corrupting the tree.
    5. ``page_index`` (page -> [seq_lo, seq_hi]) + ``section_index`` (outline).

    Pure; never touches the DB.
    """
    blocks = [b.model_copy(deep=True) for b in result.blocks]

    # 1. Page-monotonic re-sort (stable on incoming seq within a page).
    blocks.sort(key=lambda b: (b.page, b.seq))

    # 2. Contiguous seq reindex + parent_seq remap.
    old_to_new = {b.seq: i for i, b in enumerate(blocks)}
    for i, b in enumerate(blocks):
        if b.parent_seq is not None:
            b.parent_seq = old_to_new.get(b.parent_seq)
        b.seq = i
        b.subtree_end = None

    # 3. subtree_end + section_path via a heading-level stack.
    # stack entries: (level, seq, title)
    stack: List[tuple] = []
    for b in blocks:
        if b.type == BlockType.heading:
            level = b.level if b.level is not None else 1
            while stack and stack[-1][0] >= level:
                _lvl, closed_seq, _title = stack.pop()
                blocks[closed_seq].subtree_end = b.seq - 1
            b.section_path = [t for (_l, _s, t) in stack]
            stack.append((level, b.seq, b.text or ""))
        else:
            b.section_path = [t for (_l, _s, t) in stack]
    last_seq = blocks[-1].seq if blocks else -1
    while stack:
        _lvl, closed_seq, _title = stack.pop()
        blocks[closed_seq].subtree_end = last_seq

    # 4. parent_seq < seq validation.
    for b in blocks:
        if b.parent_seq is not None and not (0 <= b.parent_seq < b.seq):
            logger.warning(
                f"finalize: dropping invalid parent_seq={b.parent_seq} on seq={b.seq}"
            )
            b.parent_seq = None

    # 5. page_index + section_index.
    page_count = result.page_count or (max((b.page for b in blocks), default=0))
    page_index: List[List[int]] = []
    for page in range(1, page_count + 1):
        seqs = [b.seq for b in blocks if b.page == page]
        if seqs:
            page_index.append([min(seqs), max(seqs)])
        else:
            # Empty page: an inverted range so a scan returns nothing while the
            # list stays positionally aligned (index == page - 1).
            page_index.append([0, -1])

    section_index = [
        {
            "seq": b.seq,
            "level": b.level if b.level is not None else 1,
            "title": b.text or "",
            "subtree_end": b.subtree_end,
        }
        for b in blocks
        if b.type == BlockType.heading
    ]

    return FinalizedParse(
        parser_name=result.parser_name,
        parser_version=result.parser_version,
        page_count=page_count,
        pages=list(result.pages),
        capabilities=set(result.capabilities),
        blocks=blocks,
        page_index=page_index,
        section_index=section_index,
    )


def _field(block: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` off a block that may be a dict, ParsedBlock, or DocumentBlock."""
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def blocks_to_markdown(blocks: List[Any]) -> str:
    """Deterministic markdown from a seq-ordered block list (db-design §5).

    Accepts dicts, :class:`ParsedBlock`, or ``DocumentBlock``. Per-type mapping,
    blocks joined by a blank line:
    - heading    -> ``#``×min(level,6) + text
    - paragraph  -> text
    - list_item  -> ``- `` + text   (``list`` container -> its text, if any)
    - code       -> fenced block
    - table      -> its ``text`` (Docling md export)
    - equation   -> ``$$\\n<latex>\\n$$`` when latex present, else raw text
    - figure     -> ``![<caption or "Figure (p.N)">](block://<seq>)``
    - caption    -> ``*<text>*``
    - footnote   -> text
    - page_header / page_footer -> skipped

    Pure — no DB, no server-side LaTeX validation (Decision #7).
    """
    parts: List[str] = []
    for block in blocks:
        btype = _field(block, "type")
        btype = btype.value if isinstance(btype, BlockType) else str(btype)
        text = _field(block, "text") or ""

        if btype == BlockType.page_header or btype == BlockType.page_footer:
            continue

        if btype == BlockType.heading:
            level = _field(block, "level")
            level = level if isinstance(level, int) and level >= 1 else 1
            depth = min(level, 6)
            rendered = f"{'#' * depth} {text}".rstrip()
        elif btype == BlockType.list_item:
            rendered = f"- {text}".rstrip()
        elif btype == BlockType.code:
            rendered = f"```\n{text}\n```"
        elif btype == BlockType.equation:
            latex = _field(block, "latex")
            rendered = f"$$\n{latex}\n$$" if latex else text
        elif btype == BlockType.figure:
            seq = _field(block, "seq")
            page = _field(block, "page")
            alt = text or f"Figure (p.{page})"
            rendered = f"![{alt}](block://{seq})"
        elif btype == BlockType.caption:
            rendered = f"*{text}*" if text else ""
        else:
            # paragraph, list, table, footnote, and any future type
            rendered = text

        if rendered:
            parts.append(rendered)

    return "\n\n".join(parts)
