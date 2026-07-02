import asyncio
import base64
import mimetypes
import os
import sqlite3
from typing import Annotated, Optional

from ai_prompter import Prompter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from open_notebook.ai.claude_agent import (
    generate_with_claude_agent,
    get_claude_agent_model,
    is_claude_agent_selected,
)
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.config import CHAT_MEDIA_FOLDER, LANGGRAPH_CHECKPOINT_FILE
from open_notebook.domain.notebook import Notebook
from open_notebook.exceptions import OpenNotebookError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content


class ThreadState(TypedDict):
    messages: Annotated[list, add_messages]
    notebook: Optional[Notebook]
    context: Optional[str]
    context_config: Optional[dict]
    model_override: Optional[str]
    quote: Optional[str]


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


async def _generate_ai_message(model_id, payload, config: RunnableConfig) -> AIMessage:
    """Produce the chat AIMessage for the selected model.

    Routes to the Claude Agent SDK when the selected/default model is the
    ``claude_agent`` sentinel; otherwise uses the standard Esperanto/LangChain
    provisioning path (unchanged behavior).
    """
    if await is_claude_agent_selected(model_id):
        thread_id = config.get("configurable", {}).get("thread_id")
        agent_model = await get_claude_agent_model(model_id)
        logger.info(
            f"Chat model routing -> Claude Agent SDK | pinned_model="
            f"{agent_model or 'Claude Code default'} | override={model_id!r}"
        )
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
    return model.invoke(_attach_media_blocks(payload))


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

        # Handle async generation from sync context (reused event-loop bridging)
        def run_in_new_loop():
            """Run the async function in a new event loop"""
            new_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(new_loop)
                return new_loop.run_until_complete(
                    _generate_ai_message(model_id, payload, config)
                )
            finally:
                new_loop.close()
                asyncio.set_event_loop(None)

        try:
            # Try to get the current event loop
            asyncio.get_running_loop()
            # If we're in an event loop, run in a thread with a new loop
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop)
                ai_message = future.result()
        except RuntimeError:
            # No event loop running, safe to use asyncio.run()
            ai_message = asyncio.run(_generate_ai_message(model_id, payload, config))

        # Clean thinking content from AI response (e.g., <think>...</think> tags)
        content = extract_text_content(ai_message.content)
        cleaned_content = clean_thinking_content(content)
        cleaned_message = ai_message.model_copy(update={"content": cleaned_content})

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
