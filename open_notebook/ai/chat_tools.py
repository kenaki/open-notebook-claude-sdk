"""LangChain tools giving tool-calling-capable Esperanto chat models (e.g. ds4/
DeepSeek) the same document-navigation capability the Claude Agent SDK path
already has via ``claude_agent_tools.py`` — search across sources/notes, read a
source's chapter outline, and pull one chapter's content — instead of only ever
seeing the manually-stuffed context blob.

Kept separate from ``claude_agent_tools.py`` because that module wraps the
Agent SDK's ``@tool``/MCP contract; these use plain ``langchain_core.tools.tool``
so they can be passed straight to ``BaseChatModel.bind_tools()``.
"""

import json

from langchain_core.tools import tool

from open_notebook.domain.notebook import Source, SourceSection, text_search

# Cap individual serialized strings so one chapter can't blow the context.
_MAX_STR = 4000


def _truncate(text: str | None) -> str | None:
    if text is not None and len(text) > _MAX_STR:
        return text[:_MAX_STR] + "… [truncated]"
    return text


@tool
async def search_sources(query: str, limit: int = 5) -> str:
    """Full-text search across the user's sources and notes. Returns matching
    items (with ids) so you can drill into a specific one with
    get_source_outline / get_section instead of relying on the context already
    given to you."""
    rows = await text_search(query, limit)
    cleaned = [
        {k: v for k, v in row.items() if k not in ("embedding", "content_embedding")}
        for row in (rows or [])
    ]
    return json.dumps(
        {"query": query, "results": cleaned, "count": len(cleaned)}, default=str
    )


@tool
async def get_source_outline(source_id: str) -> str:
    """Get the chapter/section outline of a source document: title, page
    ranges, and summary for each chapter. Use this to navigate a long document
    before drilling into a specific section with get_section."""
    source = await Source.get(source_id)
    outline = await source.get_outline()
    return json.dumps(
        {"source_id": source_id, "title": source.title, "outline": outline},
        default=str,
    )


@tool
async def get_section(source_id: str, section_id: str) -> str:
    """Get the full content of one section/chapter of a document, by section id
    (from get_source_outline). Returns cleaned content when available,
    otherwise the raw parsed content."""
    section = await SourceSection.get(section_id)
    content = section.cleaned_content or section.content
    return json.dumps(
        {
            "section_id": section_id,
            "title": section.title,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "content": _truncate(content),
        },
        default=str,
    )


CHAT_TOOLS = [search_sources, get_source_outline, get_section]
