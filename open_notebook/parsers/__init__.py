"""PDF block parsers — the plugin boundary and shared post-pass.

See ``base.py`` for the contract (BlockType/BBox/PageInfo/ParsedBlock/
ParseResult/BlockParser), the shared ``finalize()`` post-pass, and the canonical
``blocks_to_markdown()`` serializer.
"""

from open_notebook.parsers.base import (
    BBox,
    BlockParser,
    BlockType,
    FinalizedParse,
    PageInfo,
    ParsedBlock,
    ParseResult,
    blocks_to_markdown,
    finalize,
)

__all__ = [
    "BBox",
    "BlockParser",
    "BlockType",
    "FinalizedParse",
    "PageInfo",
    "ParsedBlock",
    "ParseResult",
    "blocks_to_markdown",
    "finalize",
]
