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
from open_notebook.domain.recall import get_exchange_content, recall_search

# Cap individual serialized strings so one chapter can't blow the context.
_MAX_STR = 4000


def _truncate(text: str | None) -> str | None:
    if text is not None and len(text) > _MAX_STR:
        return text[:_MAX_STR] + "… [truncated]"
    return text


def _find_outline_node(nodes: list[dict], section_id: str) -> dict | None:
    """Depth-first search of an outline tree for the node with ``section_id``."""
    for node in nodes:
        if node.get("id") == section_id:
            return node
        found = _find_outline_node(node.get("children") or [], section_id)
        if found is not None:
            return found
    return None


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
async def get_source_outline(source_id: str, section_id: str = "") -> str:
    """Get the chapter/section outline of a source document: title, page
    ranges, and summary per chapter. Use this to navigate a long document
    before drilling into a specific section with get_section.

    Without section_id: a capped overview (chapters + main sections, summaries
    truncated) — cheap enough for any book. Pass a section_id from that
    overview to expand ONE chapter's full subtree (all nested subsections,
    untruncated summaries) when you need to survey a whole chapter."""
    source = await Source.get(source_id)
    if section_id:
        full = await source.get_outline()
        subtree = _find_outline_node(full, section_id)
        if subtree is None:
            return json.dumps(
                {"source_id": source_id, "error": f"section '{section_id}' not found"}
            )
        return json.dumps(
            {"source_id": source_id, "title": source.title, "outline": [subtree]},
            default=str,
        )
    # Tiered-summary caps (see Source.get_outline): levels 1–2 only,
    # summaries truncated — an uncapped 472-section outline is ~80K tokens.
    outline = await source.get_outline(max_depth=2, summary_depth=2, summary_chars=300)
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


@tool
async def search_past_discussions(query: str, limit: int = 5) -> str:
    """Search the user's PAST chat discussions and highlighted annotations for
    ones related to the current topic (study-memory recall).

    Returns METADATA ONLY — titles, snippets, and similarity scores that point
    at prior study sessions and highlights. These are pointers, NOT their
    content: you may cite them (e.g. "we touched on this before in ...") but
    you must NEVER restate, paraphrase, or guess what was concluded there from
    the metadata alone — you do not actually know. If the user asks what was
    said/concluded/highlighted, call get_past_discussion with the ref's id
    from these results to fetch the real content first."""
    refs = await recall_search(query, limit=limit)
    return json.dumps({"results": refs, "count": len(refs)}, default=str)


@tool
async def get_past_discussion(ref_id: str) -> str:
    """Fetch the FULL content of ONE past discussion or highlight, by the
    ``id`` of a result from search_past_discussions (e.g.
    "chat_exchange:abc" or "source_annotation:xyz").

    Use this ONLY when the user explicitly asks what was discussed, decided,
    or highlighted before — never call it speculatively just because
    search_past_discussions found something related."""
    content = await get_exchange_content(ref_id)
    return json.dumps(content, default=str)


CHAT_TOOLS = [
    search_sources,
    get_source_outline,
    get_section,
    search_past_discussions,
    get_past_discussion,
]
