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

from open_notebook.domain.notebook import Note, Notebook, Source, text_search

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
    "Get a source's title, topics, full text, and insights by id.",
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
            get_note,
            search,
        ],
    )
