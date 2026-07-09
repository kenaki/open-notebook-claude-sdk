import base64
import mimetypes
import os
import sqlite3
from typing import Annotated, Optional
from uuid import uuid4

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from loguru import logger
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from open_notebook.ai.chat_tools import CHAT_TOOLS
from open_notebook.ai.claude_agent import (
    generate_with_claude_agent,
    get_claude_agent_model,
    is_claude_agent_selected,
)
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.config import CHAT_MEDIA_FOLDER, LANGGRAPH_CHECKPOINT_FILE
from open_notebook.domain.notebook import Notebook
from open_notebook.exceptions import OpenNotebookError
from open_notebook.utils import parse_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.graph_utils import run_async_in_node
from open_notebook.utils.job_progress import report_job_progress
from open_notebook.utils.text_utils import extract_text_content

# Hard cap on search/outline/section round-trips per turn. Each round is a full
# model invoke, so this bounds worst-case latency (esp. for single-stream local
# models like ds4, which pay this serially with no batching).
_MAX_TOOL_ITERATIONS = 5

# Human-readable phase label per chat tool, reported live so the UI can show
# what the model is doing instead of a generic spinner during a multi-minute
# tool loop (see open_notebook.ai.chat_tools). Falls back to a generic label
# for any tool not listed here.
_TOOL_PHASE_LABELS = {
    "search_sources": "Searching your sources",
    "get_source_outline": "Reading document outline",
    "get_section": "Reading a section",
}


class ThreadState(TypedDict):
    messages: Annotated[list, add_messages]
    notebook: Optional[Notebook]
    context: Optional[str]
    context_config: Optional[dict]
    model_override: Optional[str]
    quote: Optional[str]
    # This command's own record id, so the tool loop can stamp live progress
    # (phase + which tool) onto the job row. None when not run as a job.
    job_id: Optional[str]


def _media_to_data_uri(item: dict) -> Optional[str]:
    """Read an attached image off disk and return a base64 ``data:`` URI.

    The MediaItem ``url`` is ``/api/chat/media/<filename>``; the file lives under
    ``CHAT_MEDIA_FOLDER``. We resolve by basename (path-traversal guarded) and
    inline the bytes as a data URI so the model provider does not need to reach
    back to this server. Returns ``None`` if the file can't be read.

    If the item already carries a precomputed ``data_uri`` (e.g. in-memory bytes
    that were never written to ``CHAT_MEDIA_FOLDER`` — see
    ``open_notebook.ai.vision_utils.provision_vision_message``), it is returned
    as-is and no disk lookup happens.
    """
    if item.get("data_uri"):
        return item["data_uri"]

    url = item.get("url") or ""
    safe_name = os.path.basename(url)
    if not safe_name:
        return None
    safe_root = os.path.realpath(CHAT_MEDIA_FOLDER)
    resolved = os.path.realpath(os.path.join(safe_root, safe_name))
    if resolved != safe_root and not resolved.startswith(safe_root + os.sep):
        logger.warning(f"Blocked chat-media path traversal: {url}")
        return None
    if not os.path.exists(resolved):
        logger.warning(f"Chat-media file missing on disk: {resolved}")
        return None
    mime = mimetypes.guess_type(resolved)[0] or "image/png"
    try:
        with open(resolved, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        logger.warning(f"Could not read chat-media file {resolved}: {e}")
        return None
    return f"data:{mime};base64,{encoded}"


def _attach_media_blocks(payload: list) -> list:
    """Rebuild HumanMessages carrying media into multimodal content blocks.

    For the Esperanto/LangChain (vision) path only: each HumanMessage whose
    ``additional_kwargs['media']`` is set becomes ``content=[{text}, {image_url},
    …]``. Images are inlined as data URIs; videos (no inline support) are referenced
    as text. Messages without media pass through untouched. Called only at invoke
    time so token-count provisioning still sees the original text payload.
    """
    new_payload: list = []
    for message in payload:
        extra = getattr(message, "additional_kwargs", None) or {}
        media = extra.get("media") if isinstance(extra, dict) else None
        if not (media and isinstance(message, HumanMessage)):
            new_payload.append(message)
            continue

        blocks: list = []
        text = extract_text_content(message.content)
        if text:
            blocks.append({"type": "text", "text": text})
        for item in media:
            if item.get("type") == "image":
                data_uri = _media_to_data_uri(item)
                if data_uri:
                    blocks.append(
                        {"type": "image_url", "image_url": {"url": data_uri}}
                    )
                    continue
            # Video (or an image we couldn't inline) → textual reference.
            label = item.get("label") or item.get("url") or "attachment"
            blocks.append(
                {"type": "text", "text": f"[Attached {item.get('type')}: {label}]"}
            )
        new_payload.append(message.model_copy(update={"content": blocks}))
    return new_payload


async def _run_tool_loop(
    model_with_tools, payload: list, ai_message: AIMessage, job_id: Optional[str] = None
) -> AIMessage:
    """Execute any tool calls the model made, feeding results back until it
    returns a final answer or ``_MAX_TOOL_ITERATIONS`` is hit.

    ``ai_message`` is the response from the caller's first invoke (so the no
    -tool-calls case costs nothing extra). Tool-use disclosures accumulate in
    OpenAI-shaped dicts, then get attached to the final message so the API/UI
    can render "Searched your sources" the same way it does for the Claude
    Agent path (see ``api/routers/chat/citations.py``).

    Before each tool call, stamps a live phase (+ tool name/input) onto the
    job row via ``report_job_progress`` so the chat UI can show what's
    happening instead of a bare spinner for the duration of the round-trip.
    """
    tools_by_name = {t.name: t for t in CHAT_TOOLS}
    conversation = list(payload)
    disclosures: list[dict] = []

    for _ in range(_MAX_TOOL_ITERATIONS):
        if not getattr(ai_message, "tool_calls", None):
            break
        conversation.append(ai_message)
        for call in ai_message.tool_calls:
            tool_fn = tools_by_name.get(call["name"])
            is_error = tool_fn is None
            phase = _TOOL_PHASE_LABELS.get(call["name"], f"Using {call['name']}")
            await report_job_progress(
                job_id, phase, tool_name=call["name"], tool_input=call["args"]
            )
            if tool_fn is None:
                result = f"Unknown tool: {call['name']}"
            else:
                try:
                    result = await tool_fn.ainvoke(call["args"])
                except Exception as e:
                    result = f"Tool error: {e}"
                    is_error = True
            disclosures.append(
                {
                    "id": call["id"],
                    "tool_name": call["name"],
                    "tool_input": call["args"],
                    "tool_result": str(result),
                    "is_error": is_error,
                }
            )
            conversation.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
        ai_message = model_with_tools.invoke(_attach_media_blocks(conversation))

    if disclosures:
        ai_message = ai_message.model_copy(
            update={
                "additional_kwargs": {
                    **ai_message.additional_kwargs,
                    "tool_uses": disclosures,
                }
            }
        )
    return ai_message


# --- Claude-agent slim context (AGENT-CTX N1) --------------------------------
# On the Claude Agent SDK path the pre-rendered context blob (100KB+ for
# book-sized notebooks) is redundant: the agent's unscoped
# ``mcp__open_notebook__*`` tools can fetch any source/note on demand. The
# agent branch therefore swaps the blob for a compact id+title index of the
# WHOLE notebook — deliberately ignoring the per-chat context_config, which
# was never an information boundary on this path (the tools reach everything
# regardless), so only redundant bytes are dropped, never access control.
# The Esperanto/LangChain path keeps the full blob byte-identical: those
# providers may lack tool support and need the content pushed.

_AGENT_INDEX_HEADER = (
    "Notebook source index — full content is NOT inlined. Retrieve on demand "
    "with the mcp__open_notebook__ tools (search / get_source_outline / "
    "get_section / get_source / get_note) and cite ids exactly as listed."
)

# Abstract-like fields surfaced next to an index line when the cheap listing
# already carries one. Checked in order; NEVER triggers extra per-record
# fetches (the index is built from one get_sources() + one get_notes() total).
_ABSTRACT_FIELDS = ("abstract", "summary", "description")
_MAX_ABSTRACT_CHARS = 300


def _record_field(record, name: str):
    """Read ``name`` off a record that may be a pydantic model or a dict."""
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def format_index_line(record, prefix: str) -> Optional[str]:
    """One ``- <prefix>:<id> — "<title>"[ — <abstract>]`` index line.

    Pure. Returns ``None`` when the record has no id (an id-less entry can't
    be retrieved or cited, so it is skipped). The id keeps its table prefix
    exactly once whether the record carries ``source:abc`` or a bare ``abc``.
    """
    record_id = _record_field(record, "id")
    if not record_id:
        return None
    record_id = str(record_id)
    if not record_id.startswith(f"{prefix}:"):
        record_id = f"{prefix}:{record_id}"
    title = _record_field(record, "title") or "Untitled"
    line = f'- {record_id} — "{title}"'
    for field in _ABSTRACT_FIELDS:
        value = _record_field(record, field)
        if isinstance(value, str) and value.strip():
            abstract = " ".join(value.split())
            if len(abstract) > _MAX_ABSTRACT_CHARS:
                abstract = abstract[:_MAX_ABSTRACT_CHARS].rstrip() + "…"
            line += f" — {abstract}"
            break
    return line


def build_agent_context_index(sources, notes) -> str:
    """Pure: source + note records -> compact slim-context index text.

    Input records may be domain models (``Source``/``Note``) or plain dicts;
    only id/title (+ an abstract-like field when already present) are read, so
    the cheap ``get_sources()`` / ``get_notes()`` listings are enough.
    """
    lines = [format_index_line(s, "source") for s in (sources or [])]
    lines += [format_index_line(n, "note") for n in (notes or [])]
    body = [line for line in lines if line]
    if not body:
        return (
            _AGENT_INDEX_HEADER
            + "\n\n(This notebook has no sources or notes yet.)"
        )
    return _AGENT_INDEX_HEADER + "\n\n" + "\n".join(body)


async def _slim_agent_payload(payload: list, state: Optional[ThreadState]) -> list:
    """Swap the rendered context blob in ``payload[0]`` for the slim index.

    Claude-agent branch only. Re-renders the ``chat/system`` template with
    ``context`` replaced by the whole-notebook index, so the citation rules /
    quote block / notebook header stay intact.

    Degrade, never fail: on ANY problem this returns the original payload
    untouched — the full blob plus the E2BIG stdin guard in
    ``open_notebook.ai.claude_agent`` still protect the turn.
    """
    try:
        notebook = (state or {}).get("notebook")
        if (
            notebook is None
            or not payload
            or not isinstance(payload[0], SystemMessage)
        ):
            return payload
        sources = await notebook.get_sources()  # cheap: omits full_text
        notes = await notebook.get_notes()  # cheap: omits content
        slim_state = dict(state)  # type: ignore[arg-type]
        slim_state["context"] = build_agent_context_index(sources, notes)
        slim_prompt = Prompter(prompt_template="chat/system").render(
            data=slim_state  # type: ignore[arg-type]
        )
        before = len(str(payload[0].content).encode("utf-8"))
        after = len(slim_prompt.encode("utf-8"))
        logger.info(
            f"Claude-agent slim context: system prompt {before}B -> {after}B"
        )
        return [SystemMessage(content=slim_prompt)] + payload[1:]
    except Exception as e:
        logger.warning(
            f"Claude-agent slim context failed; keeping full context blob: {e}"
        )
        return payload


async def _generate_ai_message(
    model_id,
    payload,
    config: RunnableConfig,
    job_id: Optional[str] = None,
    state: Optional[ThreadState] = None,
) -> AIMessage:
    """Produce the chat AIMessage for the selected model.

    Routes to the Claude Agent SDK when the selected/default model is the
    ``claude_agent`` sentinel. Otherwise uses the standard Esperanto/LangChain
    provisioning path, binding the search/outline/section tools (see
    ``open_notebook.ai.chat_tools``) when the model supports tool calling so it
    can navigate a chaptered document instead of only seeing the context blob.
    Models that don't support ``bind_tools`` fall back to plain chat, unchanged.

    ``state`` feeds the agent-path slim-context swap only (see
    ``_slim_agent_payload``); the Esperanto path never reads it, keeping that
    path byte-identical.
    """
    if await is_claude_agent_selected(model_id):
        thread_id = config.get("configurable", {}).get("thread_id")
        agent_model = await get_claude_agent_model(model_id)
        logger.info(
            f"Chat model routing -> Claude Agent SDK | pinned_model="
            f"{agent_model or 'Claude Code default'} | override={model_id!r}"
        )
        payload = await _slim_agent_payload(payload, state)
        return await generate_with_claude_agent(
            payload, thread_id=thread_id, model=agent_model
        )

    logger.info(
        f"Chat model routing -> Esperanto/LangChain | model_id={model_id!r}"
    )
    model = await provision_langchain_model(
        str(payload), model_id, "chat", max_tokens=8192
    )
    # Provision on the text payload (above) so token counting is unaffected by
    # large base64 blobs; inline media only for the actual invoke.
    try:
        model_with_tools = model.bind_tools(CHAT_TOOLS)
    except NotImplementedError:
        logger.debug(f"Model {model_id!r} does not support tool calling; plain chat")
        return model.invoke(_attach_media_blocks(payload))

    first_message = model_with_tools.invoke(_attach_media_blocks(payload))
    return await _run_tool_loop(model_with_tools, payload, first_message, job_id=job_id)


def call_model_with_messages(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        system_prompt = Prompter(prompt_template="chat/system").render(data=state)  # type: ignore[arg-type]
        if state.get("quote"):
            logger.debug(
                f"Chat system prompt rendered with SEED PASSAGE block:\n{system_prompt}"
            )
        payload = [SystemMessage(content=system_prompt)] + state.get("messages", [])
        model_id = config.get("configurable", {}).get("model_id") or state.get(
            "model_override"
        )
        job_id = state.get("job_id")

        # Bridge async generation into this sync LangGraph node (see
        # run_async_in_node: running-loop -> thread, no-loop -> asyncio.run).
        ai_message = run_async_in_node(
            lambda: _generate_ai_message(
                model_id, payload, config, job_id=job_id, state=state
            )
        )

        # Extract + strip thinking content from AI response (e.g., <think>...</think>
        # tags); persisted on additional_kwargs.thinking instead of discarded (A2).
        content = extract_text_content(ai_message.content)
        thinking, cleaned_content = parse_thinking_content(content)
        # Contract #5: AI messages must carry a stable `ai-` id — provider ids
        # (lc_run--*, bare UUIDs) don't survive as correlation keys for the
        # illustration sidecar, so anything unprefixed is replaced.
        stable_id = (
            ai_message.id
            if isinstance(ai_message.id, str) and ai_message.id.startswith("ai-")
            else f"ai-{uuid4().hex}"
        )
        update: dict = {"content": cleaned_content, "id": stable_id}
        if thinking:
            update["additional_kwargs"] = {
                **ai_message.additional_kwargs,
                "thinking": thinking,
            }
        cleaned_message = ai_message.model_copy(update=update)

        return {"messages": cleaned_message}
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


conn = sqlite3.connect(
    LANGGRAPH_CHECKPOINT_FILE,
    check_same_thread=False,
)
# Chat now runs in the worker process while the API only reads this checkpoint.
# WAL lets a single writer and concurrent readers coexist across processes;
# busy_timeout avoids spurious "database is locked" under brief contention.
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
memory = SqliteSaver(conn)

agent_state = StateGraph(ThreadState)
agent_state.add_node("agent", call_model_with_messages)
agent_state.add_edge(START, "agent")
agent_state.add_edge("agent", END)
graph = agent_state.compile(checkpointer=memory)
