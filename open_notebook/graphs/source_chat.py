import json
import sqlite3
from typing import Annotated, Any, Dict, List, Optional, Tuple

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from loguru import logger
from typing_extensions import TypedDict

from open_notebook.ai.claude_agent import (
    generate_with_claude_agent,
    get_claude_agent_model,
    is_claude_agent_selected,
)
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.config import LANGGRAPH_CHECKPOINT_FILE
from open_notebook.domain.notebook import Source, SourceInsight
from open_notebook.exceptions import OpenNotebookError
from open_notebook.graphs.chat import format_index_line
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.context_builder import ContextBuilder
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.graph_utils import run_async_in_node
from open_notebook.utils.text_utils import extract_text_content


class SourceChatState(TypedDict):
    messages: Annotated[list, add_messages]
    source_id: str
    source: Optional[Source]
    insights: Optional[List[SourceInsight]]
    context: Optional[str]
    model_override: Optional[str]
    context_indicators: Optional[Dict[str, List[str]]]


# --- Claude-agent slim context (AGENT-CTX N1) --------------------------------
# Mirrors chat.py: on the Claude Agent SDK path the ContextBuilder blob
# (truncated full text + every insight) is redundant — the agent's
# ``mcp__open_notebook__*`` tools can pull the outline / sections / raw text
# for this source on demand. The agent branch swaps the blob for a one-line
# source index plus a retrieval hint. The Esperanto path keeps the full blob
# byte-identical.

_SOURCE_AGENT_INDEX_HEADER = (
    "Source index — full content is NOT inlined. Retrieve on demand with the "
    "mcp__open_notebook__ tools and cite ids exactly as listed."
)

_SOURCE_AGENT_INDEX_HINT = (
    "Call mcp__open_notebook__get_source_outline on this id to see its "
    "chapters, then mcp__open_notebook__get_section for a specific section "
    "(mcp__open_notebook__get_source returns the full raw text; "
    "mcp__open_notebook__search finds passages across the workspace)."
)


def build_source_agent_context(source) -> str:
    """Pure: one source record (model or dict) -> slim source-chat context.

    Raises when the record has no id — without an id the agent cannot
    retrieve or cite anything, so the caller degrades to the full blob.
    """
    line = format_index_line(source, "source")
    if line is None:
        raise ValueError("source record has no id; cannot build slim context")
    return f"{_SOURCE_AGENT_INDEX_HEADER}\n\n{line}\n\n{_SOURCE_AGENT_INDEX_HINT}"


# --- Structured chat references (Chunk D2) -----------------------------------
# A source-chat message can carry N annotation references. The API router
# (which owns the send-message endpoint + DB access) resolves each id into a
# structured context section + a compact ``annotation_refs`` list, then piggybacks
# both onto the submitted message content through the ``ANNOTATION_CTX_SENTINEL``
# codec below. That is the ONLY router->worker channel available: the source
# branch of ``commands/chat_commands.py`` (out of this track's ownership) forwards
# only ``message`` / ``source_id`` / ``model_override`` into the graph state, so
# the resolved refs ride inside ``message`` and this node lifts them back out
# BEFORE the LLM turn — injecting the context into both prompt paths and stamping
# ``annotation_refs`` onto the (checkpointed) human message so the session-GET
# response can render pills. If a cleaner channel is later added to the command
# (an ``annotation_ids`` field on ChatCompletionInput), this codec can be dropped.

# Symbol-for-record-separator x2 — vanishingly unlikely to occur in user prose,
# so partitioning the message content on it is unambiguous.
ANNOTATION_CTX_SENTINEL = "\n␞␞ANNOTATION_CONTEXT␞␞\n"


def annotation_block_content(block: Dict[str, Any], quote_fallback: Optional[str]) -> str:
    """Render one anchored block into its AI-context string (db-design §3b).

    ``equation`` -> latex; ``figure``/``table`` -> ``figure: <caption>``; every
    other type -> its text. Falls back to the annotation's stored quote (then a
    typed placeholder) when the block carries no usable text. Pure."""
    btype = (block or {}).get("type")
    if btype == "equation":
        return (
            (block.get("latex") or block.get("text") or quote_fallback or "").strip()
            or "(equation)"
        )
    if btype in ("figure", "table"):
        caption = (block.get("text") or "").strip()
        return f"figure: {caption}" if caption else "figure: (image)"
    return (block.get("text") or quote_fallback or "").strip() or "(no text)"


def build_annotation_context_section(resolved: List[Dict[str, Any]]) -> str:
    """Build the ``REFERENCED ANNOTATION n`` context block from resolved refs.

    ``resolved`` is a list of ``{section_path, content, note}`` dicts (already
    fetched from the block substrate / quote fallback by the router). Returns ""
    for an empty list so the no-refs path stays byte-identical. Pure."""
    if not resolved:
        return ""
    lines = [
        "REFERENCED ANNOTATIONS — the user is explicitly pointing you at these "
        "passages of this source. Ground your answer in them and cite them when "
        "relevant:"
    ]
    for i, ref in enumerate(resolved, 1):
        section_path = ref.get("section_path") or []
        crumb = " > ".join(str(s) for s in section_path) if section_path else "unsectioned"
        content = (ref.get("content") or "").strip() or "(no text)"
        lines.append(f"\nREFERENCED ANNOTATION {i}: [{crumb}] {content}")
        note = ref.get("note")
        if note:
            lines.append(f"  User note: {note}")
    return "\n".join(lines)


def encode_annotation_payload(context: str, refs: List[Dict[str, Any]]) -> str:
    """Encode the resolved section + refs into a sentinel-delimited trailer.

    Appended to the user's message content by the router; :func:`extract_annotation_payload`
    reverses it in the graph node. Returns "" when there is nothing to carry."""
    if not context and not refs:
        return ""
    return ANNOTATION_CTX_SENTINEL + json.dumps(
        {"context": context, "refs": refs}, ensure_ascii=False
    )


def extract_annotation_payload(
    content: Any,
) -> Tuple[Any, str, Optional[List[Dict[str, Any]]]]:
    """Split a message content string into (clean_content, context, refs).

    Inverse of :func:`encode_annotation_payload`. Non-string content or content
    without the sentinel returns ``(content, "", None)`` unchanged. Pure."""
    if not isinstance(content, str) or ANNOTATION_CTX_SENTINEL not in content:
        return content, "", None
    head, _, tail = content.partition(ANNOTATION_CTX_SENTINEL)
    try:
        data = json.loads(tail)
    except Exception:
        return head, "", None
    return head, (data.get("context") or ""), (data.get("refs") or None)


def _slim_source_agent_payload(payload: list, prompt_data: Optional[dict]) -> list:
    """Swap the ContextBuilder blob in ``payload[0]`` for the slim source index.

    Claude-agent branch only. Re-renders the ``source_chat/system`` template
    with ``context`` replaced, so the source header / citation rules stay
    intact.

    Degrade, never fail: on ANY problem this returns the original payload
    untouched — the full blob plus the E2BIG stdin guard in
    ``open_notebook.ai.claude_agent`` still protect the turn.
    """
    try:
        source = (prompt_data or {}).get("source")
        if (
            not source
            or not payload
            or not isinstance(payload[0], SystemMessage)
        ):
            return payload
        slim_data = dict(prompt_data)  # type: ignore[arg-type]
        # Referenced-annotation context is NOT retrievable via the agent's MCP
        # tools (the anchor lives only in this turn), so it must survive the blob
        # swap — append it to the slim source index (Chunk D2).
        annotation_ctx = (prompt_data or {}).get("annotation_context") or ""
        slim_context = build_source_agent_context(source)
        if annotation_ctx:
            slim_context = f"{slim_context}\n\n{annotation_ctx}"
        slim_data["context"] = slim_context
        slim_prompt = Prompter(prompt_template="source_chat/system").render(
            data=slim_data
        )
        before = len(str(payload[0].content).encode("utf-8"))
        after = len(slim_prompt.encode("utf-8"))
        logger.info(
            f"Claude-agent slim context (source chat): system prompt "
            f"{before}B -> {after}B"
        )
        return [SystemMessage(content=slim_prompt)] + payload[1:]
    except Exception as e:
        logger.warning(
            f"Claude-agent slim source context failed; keeping full context "
            f"blob: {e}"
        )
        return payload


async def _generate_source_chat_message(
    model_id,
    payload,
    config: RunnableConfig,
    prompt_data: Optional[dict] = None,
) -> AIMessage:
    """Produce the source-chat AIMessage for the selected/default model.

    Routes to the Claude Agent SDK when the selected/default model is the
    ``claude_agent`` sentinel; otherwise uses the standard Esperanto/LangChain
    provisioning path. Mirrors ``chat.py._generate_ai_message`` so the
    ``claude_agent`` default (which Esperanto cannot provision) works in source
    chat too, instead of failing with "No model configured for default".

    ``prompt_data`` feeds the agent-path slim-context swap only (see
    ``_slim_source_agent_payload``); the Esperanto path never reads it,
    keeping that path byte-identical.
    """
    if await is_claude_agent_selected(model_id):
        thread_id = config.get("configurable", {}).get("thread_id")
        agent_model = await get_claude_agent_model(model_id)
        logger.info(
            f"Source chat model routing -> Claude Agent SDK | pinned_model="
            f"{agent_model or 'Claude Code default'} | override={model_id!r}"
        )
        payload = _slim_source_agent_payload(payload, prompt_data)
        return await generate_with_claude_agent(
            payload, thread_id=thread_id, model=agent_model
        )

    logger.info(
        f"Source chat model routing -> Esperanto/LangChain | model_id={model_id!r}"
    )
    model = await provision_langchain_model(
        str(payload), model_id, "chat", max_tokens=8192
    )
    return model.invoke(payload)


def call_model_with_source_context(
    state: SourceChatState, config: RunnableConfig
) -> dict:
    """
    Main function that builds source context and calls the model.

    This function:
    1. Uses ContextBuilder to build source-specific context
    2. Applies the source_chat Jinja2 prompt template
    3. Handles model provisioning with override support
    4. Tracks context indicators for referenced insights/content
    """
    try:
        return _call_model_with_source_context_inner(state, config)
    except OpenNotebookError:
        raise
    except Exception as e:
        error_class, user_message = classify_error(e)
        raise error_class(user_message) from e


def _call_model_with_source_context_inner(
    state: SourceChatState, config: RunnableConfig
) -> dict:
    source_id = state.get("source_id")
    if not source_id:
        raise ValueError("source_id is required in state")

    # Build source context using ContextBuilder, bridged into this sync node
    # (running-loop -> thread, no-loop -> asyncio.run; see run_async_in_node).
    context_data = run_async_in_node(
        lambda: ContextBuilder(
            source_id=source_id,
            include_insights=True,
            include_notes=False,  # Focus on source-specific content
            max_tokens=50000,  # Reasonable limit for source context
        ).build()
    )

    # Extract source and insights from context
    source = None
    insights = []
    context_indicators: dict[str, list[str | None]] = {
        "sources": [],
        "insights": [],
        "notes": [],
    }

    if context_data.get("sources"):
        source_info = context_data["sources"][0]  # First source
        source = Source(**source_info) if isinstance(source_info, dict) else source_info
        context_indicators["sources"].append(source.id)

    if context_data.get("insights"):
        for insight_data in context_data["insights"]:
            insight = (
                SourceInsight(**insight_data)
                if isinstance(insight_data, dict)
                else insight_data
            )
            insights.append(insight)
            context_indicators["insights"].append(insight.id)

    # Lift any structured annotation references the router piggybacked onto the
    # latest human message (Chunk D2). ``annotation_ctx`` is injected into BOTH
    # prompt paths; ``annotation_refs`` is stamped back onto the human message so
    # the checkpoint (and session-GET) can render reference pills. The turn sent
    # to the LLM uses the CLEAN content (sentinel stripped).
    messages = state.get("messages", [])
    annotation_ctx = ""
    updated_human = None
    payload_messages = messages
    if messages:
        last = messages[-1]
        clean_content, annotation_ctx, annotation_refs = extract_annotation_payload(
            getattr(last, "content", "")
        )
        if annotation_ctx or annotation_refs:
            cleaned_human = last.model_copy(
                update={
                    "content": clean_content,
                    "additional_kwargs": {
                        **(getattr(last, "additional_kwargs", None) or {}),
                        "annotation_refs": annotation_refs or [],
                    },
                }
            )
            # The LLM turn ALWAYS sees the sentinel-stripped content.
            payload_messages = messages[:-1] + [cleaned_human]
            # Re-emit for the checkpoint (add_messages replace-by-id) only when the
            # message already has a stable id — otherwise a re-emit would append a
            # duplicate instead of replacing.
            if getattr(last, "id", None):
                updated_human = cleaned_human

    # Format context for the prompt
    formatted_context = _format_source_context(context_data)
    if annotation_ctx:
        formatted_context = f"{formatted_context}\n\n{annotation_ctx}"

    # Build prompt data for the template
    prompt_data = {
        "source": source.model_dump() if source else None,
        "insights": [insight.model_dump() for insight in insights] if insights else [],
        "context": formatted_context,
        "annotation_context": annotation_ctx,
        "context_indicators": context_indicators,
    }

    # Apply the source_chat prompt template
    system_prompt = Prompter(prompt_template="source_chat/system").render(
        data=prompt_data
    )
    payload = [SystemMessage(content=system_prompt)] + payload_messages

    # Resolve the selected/default model id. Provisioning + invocation happen
    # inside _generate_source_chat_message so the ``claude_agent`` sentinel routes
    # to the Claude Agent SDK (Esperanto has no such provider) — mirroring chat.py.
    model_id = config.get("configurable", {}).get("model_id") or state.get(
        "model_override"
    )

    # Bridge async generation into this sync LangGraph node (see
    # run_async_in_node: running-loop -> thread, no-loop -> asyncio.run).
    ai_message = run_async_in_node(
        lambda: _generate_source_chat_message(
            model_id, payload, config, prompt_data=prompt_data
        )
    )

    # Clean thinking content from AI response (e.g., <think>...</think> tags)
    content = extract_text_content(ai_message.content)
    cleaned_content = clean_thinking_content(content)
    cleaned_message = ai_message.model_copy(update={"content": cleaned_content})

    # Update state with context information. When the turn carried annotation
    # references, re-emit the (same-id) human message so add_messages replaces it
    # with the sentinel-stripped content + persisted ``annotation_refs``.
    messages_update = (
        [updated_human, cleaned_message] if updated_human else cleaned_message
    )
    return {
        "messages": messages_update,
        "source": source,
        "insights": insights,
        "context": formatted_context,
        "context_indicators": context_indicators,
    }


def _format_source_context(context_data: Dict) -> str:
    """
    Format the context data into a readable string for the prompt.

    Args:
        context_data: Context data from ContextBuilder

    Returns:
        Formatted context string
    """
    context_parts = []

    # Add source information
    if context_data.get("sources"):
        context_parts.append("## SOURCE CONTENT")
        for source in context_data["sources"]:
            if isinstance(source, dict):
                context_parts.append(f"**Source ID:** {source.get('id', 'Unknown')}")
                context_parts.append(f"**Title:** {source.get('title', 'No title')}")
                if source.get("full_text"):
                    # Truncate full text if too long
                    full_text = source["full_text"]
                    if len(full_text) > 5000:
                        full_text = full_text[:5000] + "...\n[Content truncated]"
                    context_parts.append(f"**Content:**\n{full_text}")
                context_parts.append("")  # Empty line for separation

    # Add insights
    if context_data.get("insights"):
        context_parts.append("## SOURCE INSIGHTS")
        for insight in context_data["insights"]:
            if isinstance(insight, dict):
                context_parts.append(f"**Insight ID:** {insight.get('id', 'Unknown')}")
                context_parts.append(
                    f"**Type:** {insight.get('insight_type', 'Unknown')}"
                )
                context_parts.append(
                    f"**Content:** {insight.get('content', 'No content')}"
                )
                context_parts.append("")  # Empty line for separation

    # Add metadata
    if context_data.get("metadata"):
        metadata = context_data["metadata"]
        context_parts.append("## CONTEXT METADATA")
        context_parts.append(f"- Source count: {metadata.get('source_count', 0)}")
        context_parts.append(f"- Insight count: {metadata.get('insight_count', 0)}")
        context_parts.append(f"- Total tokens: {context_data.get('total_tokens', 0)}")
        context_parts.append("")

    return "\n".join(context_parts)


# Create SQLite checkpointer
conn = sqlite3.connect(
    LANGGRAPH_CHECKPOINT_FILE,
    check_same_thread=False,
)
# Source chat now runs in the worker; the API only reads this checkpoint. WAL +
# busy_timeout keeps cross-process reads safe against the worker's single writer.
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
memory = SqliteSaver(conn)

# Create the StateGraph
source_chat_state = StateGraph(SourceChatState)
source_chat_state.add_node("source_chat_agent", call_model_with_source_context)
source_chat_state.add_edge(START, "source_chat_agent")
source_chat_state.add_edge("source_chat_agent", END)
source_chat_graph = source_chat_state.compile(checkpointer=memory)
