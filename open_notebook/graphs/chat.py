import base64
import json
import mimetypes
import os
import sqlite3
import time
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
from open_notebook.domain.recall import dedupe_and_cap_recall_refs
from open_notebook.exceptions import OpenNotebookError
from open_notebook.utils import parse_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.graph_utils import run_async_in_node
from open_notebook.utils.job_progress import (
    append_job_event,
    report_job_progress,
    report_partial_content,
)
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
    "search_past_discussions": "Recalling past discussions",
    "get_past_discussion": "Reading a past discussion",
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
    # Pre-built REFERENCED-ANNOTATION section (cross-study B1): the router
    # resolved the user's annotation_ids into this prompt block and forwarded it
    # as typed state; the model-call node appends it to the assembled context.
    annotation_context: Optional[str]


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


# Live-thinking streaming (A3). Flush a thinking delta into the job event log
# whenever ~this many seconds OR ~this many new content chars have accrued since
# the last flush — a coalescing cadence so we emit readable chunks rather than a
# per-token firehose. Thinking events are capped, then one truncation marker
# (the full thinking still lands on the persisted message — see A2).
_THINKING_FLUSH_SECONDS = 2.0
_THINKING_FLUSH_CHARS = 400
_MAX_THINKING_EVENTS = 150


def extract_thinking(ai_message: AIMessage, content: str) -> tuple:
    """Normalize this turn's thinking text into ``(thinking, cleaned_content)``.

    Shared by ``chat.py``'s and ``source_chat.py``'s capture sites (A6). Never
    overwrites a ``thinking`` value a prior step (e.g. the Claude-agent path's
    ``ThinkingBlock`` capture, A4) already set on ``additional_kwargs`` — that
    text is already final and ``content`` already clean. Otherwise, first hit
    wins:
      1. ``additional_kwargs["reasoning_content"]`` — Ollama's ``reasoning``
         model field, when enabled (A6; see ``provision_langchain_model``)
      2. ``parse_thinking_content(content)`` — inline ``<think>`` tag split
         (A2), still correct for any model that emits tags instead

    ``content`` should already be the message's extracted text content.
    """
    existing = ai_message.additional_kwargs.get("thinking")
    if isinstance(existing, str) and existing.strip():
        return existing, content

    reasoning = ai_message.additional_kwargs.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning, content

    return parse_thinking_content(content)


async def _stream_model(model, messages, job_id: Optional[str] = None) -> AIMessage:
    """Invoke ``model`` on ``messages``, streaming token deltas so the model's
    thinking can tail into the job's ``progress.events[]`` log DURING generation.

    Accumulates the streamed ``AIMessageChunk``s into one message — equivalent to
    ``.invoke()``, including ``.tool_calls`` (verified by the A3 ``.astream()``
    spike against the local Ollama chat model). Every ``_THINKING_FLUSH_SECONDS``
    OR ``_THINKING_FLUSH_CHARS`` new content chars, re-parses the accumulated
    buffer with ``parse_thinking_content`` and appends the thinking **delta since
    the last flush** as a ``thinking`` event. After ``_MAX_THINKING_EVENTS``
    thinking events, one ``phase`` truncation marker is emitted and further
    thinking is dropped.

    Reasoning arrives one of two ways, both handled by ``extract_thinking``:
    Ollama's separate ``reasoning_content`` field (A6, when the provisioned
    model has ``reasoning=True`` — see ``provision_langchain_model``) accumulates
    on ``additional_kwargs`` across chunks exactly like ``content`` does (both
    are plain string concat via LangChain's chunk-merge); or inline ``<think>``
    tags in the content buffer (A2's ``parse_thinking_content`` fallback, for
    any model that emits tags instead). Today's configured local models without
    ``reasoning`` enabled (nemotron-3-super, qwen3.6) emit neither, so this
    remains a no-op for them — the correct seam either way.

    When ``job_id`` is ``None`` there is nowhere to stream events to, so this
    falls back to a plain (non-streamed) ``.invoke()`` — byte-identical result.
    """
    if job_id is None:
        return model.invoke(messages)

    accumulated = None
    emitted_thinking_len = 0
    thinking_events = 0
    truncated = False
    last_flush_time = time.monotonic()
    chars_at_last_flush = 0
    reasoning_chars_at_last_flush = 0

    def _reasoning_len(message) -> int:
        reasoning = message.additional_kwargs.get("reasoning_content") if message else None
        return len(reasoning) if isinstance(reasoning, str) else 0

    async def flush() -> None:
        nonlocal emitted_thinking_len, thinking_events, truncated
        nonlocal last_flush_time, chars_at_last_flush, reasoning_chars_at_last_flush
        text = extract_text_content(accumulated.content) if accumulated else ""
        last_flush_time = time.monotonic()
        chars_at_last_flush = len(text)
        reasoning_chars_at_last_flush = _reasoning_len(accumulated)
        thinking, cleaned = extract_thinking(accumulated, text) if accumulated else ("", text)
        # Stream the answer-so-far (thinking stripped) into a scalar progress
        # field the chat bubble renders live — overwritten each flush, so no
        # event-cap drift. Stamped before the truncated/no-delta early returns
        # so the answer keeps streaming even after the thinking log is capped.
        if cleaned:
            await report_partial_content(job_id, cleaned)
        if truncated:
            return
        delta = thinking[emitted_thinking_len:]
        if not delta:
            return
        # Advance past what we've now accounted for BEFORE emitting, so the next
        # flush's delta never re-includes or overlaps this text.
        emitted_thinking_len = len(thinking)
        if thinking_events >= _MAX_THINKING_EVENTS:
            truncated = True
            await append_job_event(
                job_id,
                "phase",
                phase="…thinking log truncated",
                label="…thinking log truncated",
            )
            return
        thinking_events += 1
        await append_job_event(job_id, "thinking", text=delta)

    async for chunk in model.astream(messages):
        accumulated = chunk if accumulated is None else accumulated + chunk
        text_len = len(extract_text_content(accumulated.content))
        reasoning_len = _reasoning_len(accumulated)
        if (
            text_len - chars_at_last_flush >= _THINKING_FLUSH_CHARS
            or reasoning_len - reasoning_chars_at_last_flush >= _THINKING_FLUSH_CHARS
            or time.monotonic() - last_flush_time >= _THINKING_FLUSH_SECONDS
        ):
            await flush()

    # Final flush: capture any thinking delta accrued after the last threshold
    # (e.g. a closing </think> in the last chunk).
    await flush()

    if accumulated is None:
        # Empty stream — fall back so the caller still gets a well-formed message.
        return model.invoke(messages)
    return accumulated


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

    Recall refs (study-memory, chunk B1): whenever ``search_past_discussions``
    returns cleanly, its metadata-only ``results`` are collected into
    ``recall_refs`` alongside ``disclosures``, then deduped/capped (see
    ``open_notebook.domain.recall.dedupe_and_cap_recall_refs``) and attached
    to the final message as ``additional_kwargs["recall_refs"]`` — same seam
    as ``tool_uses``, only when non-empty.
    """
    tools_by_name = {t.name: t for t in CHAT_TOOLS}
    conversation = list(payload)
    disclosures: list[dict] = []
    recall_refs: list[dict] = []

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
            # Structured tool-call event for the agent console (alongside the
            # back-compat phase/label above): what the model is about to run.
            await append_job_event(
                job_id,
                "tool_call",
                tool_name=call["name"],
                tool_input=call["args"],
            )
            if tool_fn is None:
                result = f"Unknown tool: {call['name']}"
            else:
                try:
                    result = await tool_fn.ainvoke(call["args"])
                except Exception as e:
                    result = f"Tool error: {e}"
                    is_error = True
            if call["name"] == "search_past_discussions" and not is_error:
                try:
                    recall_refs.extend(json.loads(result).get("results") or [])
                except (TypeError, ValueError):
                    logger.warning(
                        f"search_past_discussions returned non-JSON result: {result!r}"
                    )
            # …and the result (truncated preview) once it returns.
            await append_job_event(
                job_id,
                "tool_result",
                tool_name=call["name"],
                preview=str(result)[:500],
                is_error=is_error,
            )
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
        ai_message = await _stream_model(
            model_with_tools, _attach_media_blocks(conversation), job_id
        )

    kwargs_update: dict = {}
    if disclosures:
        kwargs_update["tool_uses"] = disclosures
    if recall_refs:
        kwargs_update["recall_refs"] = dedupe_and_cap_recall_refs(recall_refs)
    if kwargs_update:
        ai_message = ai_message.model_copy(
            update={
                "additional_kwargs": {
                    **ai_message.additional_kwargs,
                    **kwargs_update,
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
        slim_context = build_agent_context_index(sources, notes)
        # Re-append the REFERENCED-ANNOTATION section (cross-study B1): this path
        # rebuilds context from scratch, so the annotation block appended in
        # call_model_with_messages would otherwise be dropped here.
        annotation_ctx = (state or {}).get("annotation_context") or ""
        if annotation_ctx:
            slim_context = f"{slim_context}\n\n{annotation_ctx}"
        slim_state["context"] = slim_context
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
            payload, thread_id=thread_id, model=agent_model, job_id=job_id
        )

    logger.info(
        f"Chat model routing -> Esperanto/LangChain | model_id={model_id!r}"
    )
    model = await provision_langchain_model(
        str(payload), model_id, "chat", max_tokens=8192, reasoning=True
    )
    # Provision on the text payload (above) so token counting is unaffected by
    # large base64 blobs; inline media only for the actual invoke.
    try:
        model_with_tools = model.bind_tools(CHAT_TOOLS)
    except NotImplementedError:
        logger.debug(f"Model {model_id!r} does not support tool calling; plain chat")
        return model.invoke(_attach_media_blocks(payload))

    first_message = await _stream_model(
        model_with_tools, _attach_media_blocks(payload), job_id
    )
    return await _run_tool_loop(model_with_tools, payload, first_message, job_id=job_id)


def call_model_with_messages(state: ThreadState, config: RunnableConfig) -> dict:
    try:
        # Append the pre-built REFERENCED-ANNOTATION section (cross-study B1) to
        # the context the system prompt renders from, mirroring source_chat's
        # context-assembly seam. The Esperanto path consumes this rendered prompt
        # directly; the Claude-agent path re-appends the same section itself in
        # _slim_agent_payload (which rebuilds context from scratch).
        annotation_ctx = state.get("annotation_context") or ""
        render_state = state
        if annotation_ctx:
            base_context = state.get("context") or ""
            render_state = {
                **state,
                "context": f"{base_context}\n\n{annotation_ctx}".strip(),
            }
        system_prompt = Prompter(prompt_template="chat/system").render(data=render_state)  # type: ignore[arg-type]
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
        # tags, or Ollama's reasoning_content field, A6); persisted on
        # additional_kwargs.thinking instead of discarded (A2/A6).
        content = extract_text_content(ai_message.content)
        thinking, cleaned_content = extract_thinking(ai_message, content)
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
