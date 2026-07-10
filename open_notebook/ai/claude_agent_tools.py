"""In-process MCP tools exposing Open Notebook data to the Claude Agent.

These tools run inside the Agent SDK's event loop, which (via the chat node's
bridging) is a fresh loop created in a worker thread. DB access is safe because
every ``repo_query`` opens its OWN ``AsyncSurreal`` connection on the current loop
and closes it (there is no shared/global, loop-bound connection — see
``open_notebook/database/repository.py``), so callbacks invoked on the SDK loop
work without marshalling. Validated in Chunk 4 with ``list_notebooks``.

Tools follow the SDK contract: ``@tool(name, description, {param: type})`` wrapping
an ``async def fn(args: dict)`` that returns ``{"content": [{"type": "text", ...}]}``.
Bundled via ``create_sdk_mcp_server`` and referenced as ``mcp__open_notebook__<tool>``.
"""

import json
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from open_notebook.domain.notebook import (
    Note,
    Notebook,
    Source,
    SourceSection,
    text_search,
)
from open_notebook.domain.recall import get_exchange_content, recall_search

MCP_SERVER_NAME = "open_notebook"

# Cap individual serialized strings so a huge source body can't blow the context.
_MAX_STR = 4000


def _result(payload: Any) -> dict:
    """Wrap a JSON-serializable payload as an MCP text-content result."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, default=str, ensure_ascii=False),
            }
        ]
    }


def _truncate(text: str | None) -> str | None:
    if text is not None and len(text) > _MAX_STR:
        return text[:_MAX_STR] + "… [truncated]"
    return text


def _sanitize(obj: Any) -> Any:
    """Drop embedding vectors and cap long strings in raw search rows."""
    if isinstance(obj, dict):
        return {
            k: _sanitize(v)
            for k, v in obj.items()
            if k not in ("embedding", "content_embedding")
        }
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, str):
        return _truncate(obj)
    return obj


@tool(
    "list_notebooks",
    "List the user's Open Notebook notebooks (id, name, description, archived).",
    {},
)
async def list_notebooks(args: dict) -> dict:
    notebooks = await Notebook.get_all()
    data = [
        {
            "id": nb.id,
            "name": nb.name,
            "description": nb.description,
            "archived": nb.archived,
        }
        for nb in notebooks
    ]
    return _result({"notebooks": data, "count": len(data)})


@tool("get_notebook", "Get a single notebook's details by id.", {"notebook_id": str})
async def get_notebook(args: dict) -> dict:
    nb = await Notebook.get(args["notebook_id"])
    return _result(
        {
            "id": nb.id,
            "name": nb.name,
            "description": nb.description,
            "archived": nb.archived,
        }
    )


@tool(
    "list_sources",
    "List the sources in a notebook (id, title, topics; full text omitted).",
    {"notebook_id": str},
)
async def list_sources(args: dict) -> dict:
    nb = await Notebook.get(args["notebook_id"])
    sources = await nb.get_sources()
    data = [{"id": s.id, "title": s.title, "topics": s.topics} for s in sources]
    return _result(
        {"notebook_id": args["notebook_id"], "sources": data, "count": len(data)}
    )


@tool(
    "get_source",
    "Get a source's title, topics, full text, and insights by id. For long/chaptered "
    "documents, prefer get_source_outline to navigate chapters and get_section to read "
    "a specific chapter instead of the full text.",
    {"source_id": str},
)
async def get_source(args: dict) -> dict:
    s = await Source.get(args["source_id"])
    insights = await s.get_insights()
    return _result(
        {
            "id": s.id,
            "title": s.title,
            "topics": s.topics,
            "full_text": _truncate(s.full_text),
            "insights": [
                {"insight_type": i.insight_type, "content": i.content}
                for i in insights
            ],
            "hint": "Use get_source_outline to navigate chapters and get_section to "
            "read a specific chapter.",
        }
    )


@tool("get_note", "Get a note's title and content by id.", {"note_id": str})
async def get_note(args: dict) -> dict:
    n = await Note.get(args["note_id"])
    return _result(
        {
            "id": n.id,
            "title": n.title,
            "note_type": n.note_type,
            "content": _truncate(n.content),
        }
    )


@tool(
    "search",
    "Full-text search across the user's sources and notes; returns matching items.",
    {"query": str, "limit": int},
)
async def search(args: dict) -> dict:
    try:
        limit = int(args.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    rows = await text_search(args["query"], limit)
    cleaned = _sanitize(rows) if rows else []
    return _result(
        {"query": args["query"], "results": cleaned, "count": len(cleaned)}
    )


@tool(
    "get_source_outline",
    "Get the chapter/section outline of a source document. Returns title, page "
    "ranges, and summary for each chapter. Use this to navigate a long document "
    "before drilling into a specific section. Without section_id: a capped "
    "overview (chapters + main sections, summaries truncated). Pass a "
    "section_id from that overview to expand ONE chapter's full subtree.",
    {
        "type": "object",
        "properties": {
            "source_id": {"type": "string"},
            "section_id": {
                "type": "string",
                "description": "Optional: expand this section's full subtree",
            },
        },
        "required": ["source_id"],
    },
)
async def get_source_outline(args: dict) -> dict:
    source = await Source.get(args["source_id"])
    section_id = args.get("section_id") or ""
    if section_id:
        from open_notebook.ai.chat_tools import _find_outline_node

        full = await source.get_outline()
        subtree = _find_outline_node(full, section_id)
        if subtree is None:
            return _result(
                {
                    "source_id": args["source_id"],
                    "error": f"section '{section_id}' not found",
                }
            )
        return _result(
            {
                "source_id": args["source_id"],
                "title": source.title,
                "outline": [subtree],
            }
        )
    # Tiered-summary caps (see Source.get_outline) — an uncapped 472-section
    # outline is ~80K tokens once summaries are populated.
    outline = await source.get_outline(max_depth=2, summary_depth=2, summary_chars=300)
    return _result(
        {
            "source_id": args["source_id"],
            "title": source.title,
            "outline": outline,
        }
    )


@tool(
    "get_section",
    "Get the full content of a specific section of a document by section ID (from "
    "get_source_outline). Returns cleaned content when available, otherwise raw "
    "parsed content.",
    {"source_id": str, "section_id": str},
)
async def get_section(args: dict) -> dict:
    from open_notebook.ai.chat_tools import _gather_descendant_content

    section = await SourceSection.get(args["section_id"])
    content = section.cleaned_content or section.content
    # Chapter nodes carry no body of their own — their text lives in child
    # sections. Stitch descendant content together so summarize/quiz get the
    # actual prose instead of an empty string (which made the model fall back to
    # describing the section's metadata: title / page / summary: null).
    if not (content and content.strip()):
        content = await _gather_descendant_content(
            str(section.source or args["source_id"]), args["section_id"]
        )
    return _result(
        {
            "section_id": args["section_id"],
            "title": section.title,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "content": _truncate(content),
        }
    )


@tool(
    "search_past_discussions",
    "Search the user's PAST chat discussions and highlighted annotations for "
    "ones related to the current topic (study-memory recall). Returns "
    "METADATA ONLY — titles, snippets, and similarity scores that point at "
    "prior study sessions and highlights. These are pointers, NOT their "
    "content: you may cite them (e.g. \"we touched on this before in ...\") "
    "but you must NEVER restate, paraphrase, or guess what was concluded "
    "there from the metadata alone — you do not actually know. If the user "
    "asks what was said/concluded/highlighted, call get_past_discussion with "
    "the ref's id from these results to fetch the real content first.",
    {"query": str, "limit": int},
)
async def search_past_discussions(args: dict) -> dict:
    try:
        limit = int(args.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    refs = await recall_search(args["query"], limit=limit)
    return _result({"results": refs, "count": len(refs)})


@tool(
    "get_past_discussion",
    "Fetch the FULL content of ONE past discussion or highlight, by the "
    "``id`` of a result from search_past_discussions (e.g. "
    "\"chat_exchange:abc\" or \"source_annotation:xyz\"). Use this ONLY when "
    "the user explicitly asks what was discussed, decided, or highlighted "
    "before — never call it speculatively just because search_past_discussions "
    "found something related.",
    {"ref_id": str},
)
async def get_past_discussion(args: dict) -> dict:
    content = await get_exchange_content(args["ref_id"])
    return _result(content)


def build_open_notebook_mcp_server():
    """Build the in-process MCP server exposing the Open Notebook data tools."""
    return create_sdk_mcp_server(
        name=MCP_SERVER_NAME,
        version="1.0.0",
        tools=[
            list_notebooks,
            get_notebook,
            list_sources,
            get_source,
            get_source_outline,
            get_section,
            get_note,
            search,
            search_past_discussions,
            get_past_discussion,
        ],
    )
