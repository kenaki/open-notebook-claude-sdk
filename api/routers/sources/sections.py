from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.models import SourceSectionNode, SourceSectionResponse
from open_notebook.domain.notebook import Source

router = APIRouter()


def _dict_to_node(node: Dict, include_content: bool) -> SourceSectionNode:
    """Recursively convert a section dict (from get_sections / get_outline) to SourceSectionNode.

    - summary is always included (lightweight metadata).
    - content is populated only when include_content=True, preferring cleaned_content
      when available (Decision #9: viewer renders cleaned content).
    - children are processed recursively.
    """
    content: Optional[str] = None
    if include_content:
        content = node.get("cleaned_content") or node.get("content")

    return SourceSectionNode(
        id=str(node["id"]),
        title=node.get("title", ""),
        level=node.get("level", 1),
        order=node.get("order", 0),
        page_start=node.get("page_start"),
        page_end=node.get("page_end"),
        summary=node.get("summary"),
        content=content,
        children=[_dict_to_node(child, include_content) for child in node.get("children", [])],
    )


@router.get("/sources/{source_id}/sections", response_model=SourceSectionResponse)
async def get_source_sections(source_id: str, include_content: bool = False):
    """Return the chapter/section tree for a source.

    Query params:
    - include_content (bool, default False): when True, each section node includes
      its cleaned text content. Keep False (default) for TOC/outline payloads.

    When include_content=False, uses Source.get_outline() (no content column fetched).
    When include_content=True, uses Source.get_sections() (full rows, cleaned_content preferred).
    """
    try:
        # Existence/metadata check only (title is used below) — OMIT the heavy
        # body fields (db-design §6 waste #3/#5).
        source = await Source.get_meta(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        if include_content:
            # Full rows — needed to serve cleaned_content / content
            sections_dicts = await source.get_sections()
        else:
            # Outline only — lightweight: id, title, level, order, page_start, page_end, summary
            sections_dicts = await source.get_outline()

        section_nodes = [_dict_to_node(s, include_content) for s in sections_dicts]

        return SourceSectionResponse(
            id=source_id,
            title=source.title,
            has_sections=len(section_nodes) > 0,
            sections_count=len(section_nodes),
            sections=section_nodes,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching sections for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching sections: {str(e)}")
