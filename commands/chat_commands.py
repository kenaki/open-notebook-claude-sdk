"""Background chat-completion command.

Runs the notebook- or source-chat LangGraph **in the worker process** so a slow
local-model turn (ds4 cold start, Ollama, Claude Agent) becomes a tracked
background job instead of a blocking HTTP request. The worker is the sole writer
of the LangGraph SQLite checkpoint (the API only reads it), which is why all chat
invokes now live here.

Design notes:
- ``graph.invoke()`` is **sync and blocking** for the whole generation, so we run
  it via ``asyncio.to_thread`` to avoid stalling the worker's event loop (which
  also lets the graph's internal async bridge take the clean ``asyncio.run``
  path). Concurrent jobs keep flowing on the other worker slots.
- Heavy local models are serialized through the process-wide ``heavy_lane`` lock
  (ds4 single-stream constraint); cloud chats skip the lock and stay parallel.
- The full assistant message is persisted to the checkpoint by the graph; the
  frontend reads it back via ``GET /chat/sessions/{id}``. This command's output
  only reports success/failure + identity, so the job ``result`` stays small.
"""

import asyncio
import time
from typing import Optional, Tuple

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command, submit_command

from commands._heavy_lane import heavy_lane, is_heavy_model
from open_notebook.domain.notebook import ChatSession, Notebook
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.graphs.source_chat import source_chat_graph
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.job_progress import append_job_event
from open_notebook.utils.text_utils import extract_text_content


class ChatCompletionInput(CommandInput):
    session_id: str
    message: str
    context: Optional[str] = None
    model_override: Optional[str] = None
    media: list[dict] = []
    kind: str = "notebook"  # "notebook" | "source"
    source_id: Optional[str] = None
    notebook_id: Optional[str] = None
    label: str = ""  # short display label for the background-jobs tray
    # Structured source-chat annotation refs (Chunk D2), resolved by the router
    # and forwarded as typed fields instead of piggybacked on message content:
    # ``annotation_context`` is the REFERENCED-ANNOTATION prompt section,
    # ``annotation_refs`` the compact list rendered as pills by the session-GET.
    annotation_context: Optional[str] = None
    annotation_refs: list[dict] = []


class ChatCompletionOutput(CommandOutput):
    success: bool
    session_id: str
    kind: str = "notebook"
    processing_time: float = 0.0
    error_message: Optional[str] = None


def _prefixed(value: str, table: str) -> str:
    return value if value.startswith(f"{table}:") else f"{table}:{value}"


async def _run_graph(graph, state_values: dict, thread_id: str, model_override):
    """Invoke a (sync, blocking) chat graph off the event loop, serializing
    heavy local models through the shared lane."""
    config = RunnableConfig(
        configurable={"thread_id": thread_id, "model_id": model_override}
    )

    if await is_heavy_model(model_override):
        async with heavy_lane:
            logger.debug(f"chat_completion acquired heavy lane (thread={thread_id})")
            return await asyncio.to_thread(graph.invoke, state_values, config=config)
    return await asyncio.to_thread(graph.invoke, state_values, config=config)


def _new_ai_message_id(graph_result) -> Optional[str]:
    """Return the stable ``.id`` of the AI message this turn produced.

    Scans the final graph state's messages newest-first for an AI message whose
    id carries the stable ``ai-`` prefix (assigned in ``graphs/chat.py``, B3).
    Only such ids can carry a ``chat_message_media`` sidecar (B5 hydrates by that
    prefix), so anything else is not illustratable. Returns ``None`` if absent.
    """
    if not isinstance(graph_result, dict):
        return None
    for msg in reversed(graph_result.get("messages") or []):
        if getattr(msg, "type", None) == "ai":
            mid = getattr(msg, "id", None)
            if isinstance(mid, str) and mid.startswith("ai-"):
                return mid
    return None


def _last_ai_message_text_and_id(
    graph_result,
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(content, id)`` of the final AI message this turn produced.

    Unlike ``_new_ai_message_id`` (which only accepts the stable ``ai-``
    form the notebook chat graph stamps), this accepts whatever id the
    message actually carries — the source-chat graph does not stamp a
    stable id and study-memory's mirror hook may not edit graphs
    (coordinator decision 6), so it must work with either. Returns
    ``(None, None)`` if the graph result carries no AI message.
    """
    if not isinstance(graph_result, dict):
        return None, None
    for msg in reversed(graph_result.get("messages") or []):
        if getattr(msg, "type", None) == "ai":
            content = extract_text_content(getattr(msg, "content", None))
            mid = getattr(msg, "id", None)
            return content, (mid if isinstance(mid, str) else None)
    return None, None


async def _maybe_mirror_chat_exchange(
    input_data: "ChatCompletionInput", graph_result, full_session_id: str
) -> None:
    """Fire-and-forget the ``mirror_chat_exchange`` study-memory job.

    Runs for BOTH notebook and source chats (coordinator decision 6: one
    mirror command, submitted post-``graph.invoke`` in both branches, no
    graph edits). Skipped entirely when the turn produced no usable AI
    content — a mirror failure (or absence) must never affect the chat
    turn, and failed/empty turns are not worth mirroring. The whole thing
    is wrapped by the caller in try/except as an extra safety net.
    """
    answer, message_id = _last_ai_message_text_and_id(graph_result)
    if not answer or not answer.strip():
        logger.debug("mirror_chat_exchange: no AI content produced; skipping")
        return

    # Defensive: the graph nodes already strip thinking into
    # additional_kwargs before this point, but guarantee it here too.
    answer = clean_thinking_content(answer)
    if not answer.strip():
        logger.debug("mirror_chat_exchange: content was thinking-only; skipping")
        return

    scope = "source" if input_data.kind == "source" else "notebook"
    source_id = (
        _prefixed(input_data.source_id, "source")
        if scope == "source" and input_data.source_id
        else None
    )
    notebook_id = (
        _prefixed(input_data.notebook_id, "notebook")
        if scope == "notebook" and input_data.notebook_id
        else None
    )
    annotation_ids = (
        [ref["id"] for ref in input_data.annotation_refs]
        if scope == "source" and input_data.annotation_refs
        else []
    )

    # Ensure the command is registered before submitting (submit_command
    # validates against the local registry — mirror the illustration
    # trigger below).
    import commands.study_memory_commands  # noqa: F401

    command_id = submit_command(
        "open_notebook",
        "mirror_chat_exchange",
        {
            "session_id": full_session_id,
            "scope": scope,
            "source_id": source_id,
            "notebook_id": notebook_id,
            "question": input_data.message,
            "answer": answer,
            "message_id": message_id or "",
            "annotation_ids": annotation_ids,
        },
    )
    logger.info(
        f"mirror_chat_exchange: submitted job {command_id} "
        f"for session {full_session_id} (scope={scope})"
    )


async def _maybe_trigger_illustration(
    input_data: "ChatCompletionInput", graph_result, model_override
) -> None:
    """Fire-and-forget the ``illustrate_message`` enrichment job (contract #6 v2).

    Only for notebook chats (``kind == "notebook"``) whose notebook has
    ``auto_illustrate`` on (default true) and where the turn produced a stable AI
    message id. Submits BEFORE the chat job returns so the active-jobs poller sees
    the illustration job in the same window (no discovery gap). The whole thing is
    wrapped by the caller in try/except — a trigger failure must NEVER fail the
    chat job.
    """
    if input_data.kind != "notebook" or not input_data.notebook_id:
        return
    message_id = _new_ai_message_id(graph_result)
    if not message_id:
        logger.debug("auto-illustrate: no stable ai- message id produced; skipping")
        return

    notebook = await Notebook.get(input_data.notebook_id)
    auto = getattr(notebook, "auto_illustrate", True) if notebook else True
    if auto is None:
        auto = True
    if not auto:
        logger.debug("auto-illustrate: notebook toggle OFF; skipping")
        return

    # Ensure the command is registered before submitting (submit_command validates
    # against the local registry — mirror api/podcast_service.py).
    import commands.illustrate_commands  # noqa: F401

    job_id = submit_command(
        "open_notebook",
        "illustrate_message",
        {
            "session_id": input_data.session_id,
            "message_id": message_id,
            "notebook_id": input_data.notebook_id,
            "model_id": model_override,
            "label": input_data.label or "",
        },
    )
    logger.info(
        f"auto-illustrate: submitted illustrate_message job {job_id} "
        f"for message {message_id}"
    )


@command("chat_completion", app="open_notebook", retry={"max_attempts": 1})
async def chat_completion_command(
    input_data: ChatCompletionInput,
) -> ChatCompletionOutput:
    """Execute a notebook- or source-chat turn as a background job."""
    start_time = time.time()
    full_session_id = _prefixed(input_data.session_id, "chat_session")

    try:
        session = await ChatSession.get(full_session_id)
        if not session:
            raise ValueError("Session not found")

        # This command's own record id, so the chat graph's tool loop can
        # stamp live progress (phase + tool) onto the job row for the UI.
        job_id = (
            str(input_data.execution_context.command_id)
            if input_data.execution_context
            else None
        )

        # Record what context this turn was given (console visibility, A5) —
        # only the notebook-chat path forwards a context blob via input_data.
        if input_data.context:
            await append_job_event(
                job_id,
                "context",
                chars=len(input_data.context),
                preview=input_data.context[:1000],
            )

        # Model override: explicit arg wins, else the session-level setting.
        model_override = (
            input_data.model_override
            if input_data.model_override is not None
            else getattr(session, "model_override", None)
        )

        if input_data.kind == "source":
            graph = source_chat_graph
            current_state = await asyncio.to_thread(
                source_chat_graph.get_state,
                config=RunnableConfig(
                    configurable={"thread_id": full_session_id}
                ),
            )
            state_values = current_state.values if current_state else {}
            state_values["messages"] = state_values.get("messages", [])
            state_values["source_id"] = _prefixed(input_data.source_id or "", "source")
            state_values["model_override"] = model_override
            state_values["job_id"] = job_id
            # Structured annotation refs (Chunk D2) travel as typed state, not in
            # message content: the resolved REFERENCED-ANNOTATION section goes into
            # graph state and the compact refs list rides on the human message's
            # additional_kwargs so the checkpoint (and session-GET) render pills.
            state_values["annotation_context"] = input_data.annotation_context or ""
            additional_kwargs = (
                {"annotation_refs": input_data.annotation_refs}
                if input_data.annotation_refs
                else {}
            )
            state_values["messages"].append(
                HumanMessage(
                    content=input_data.message, additional_kwargs=additional_kwargs
                )
            )
        else:
            graph = chat_graph
            notebook = None
            if input_data.notebook_id:
                notebook = await Notebook.get(input_data.notebook_id)

            current_state = await asyncio.to_thread(
                chat_graph.get_state,
                config=RunnableConfig(
                    configurable={"thread_id": full_session_id}
                ),
            )
            state_values = current_state.values if current_state else {}
            state_values["messages"] = state_values.get("messages", [])
            state_values["context"] = input_data.context
            state_values["notebook"] = notebook
            state_values["model_override"] = model_override
            state_values["quote"] = getattr(session, "quote", None)
            state_values["job_id"] = job_id
            # Structured annotation refs (cross-study B1) travel as typed state,
            # not in message content — mirroring the source branch: the resolved
            # REFERENCED-ANNOTATION section goes into graph state and the compact
            # refs list rides on the human message's additional_kwargs so the
            # checkpoint (and session-GET) render pills.
            state_values["annotation_context"] = input_data.annotation_context or ""

            additional_kwargs = {}
            if input_data.media:
                additional_kwargs["media"] = input_data.media
            if input_data.annotation_refs:
                additional_kwargs["annotation_refs"] = input_data.annotation_refs
            state_values["messages"].append(
                HumanMessage(
                    content=input_data.message, additional_kwargs=additional_kwargs
                )
            )

        graph_result = await _run_graph(
            graph, state_values, full_session_id, model_override
        )

        # Touch the session's updated timestamp (mirrors the old endpoint).
        await session.save()

        # Study-memory mirror (Track A, Chunk A3): fire-and-forget
        # mirror_chat_exchange for BOTH notebook and source chats
        # (coordinator decision 6). Best-effort — any failure is logged and
        # swallowed so it can never fail the chat turn.
        try:
            await _maybe_mirror_chat_exchange(input_data, graph_result, full_session_id)
        except Exception as e:
            logger.warning(f"mirror_chat_exchange trigger skipped (swallowed): {e}")

        # Auto-illustrate trigger (chat-foundation W1, frozen contract #6 v2):
        # fire-and-forget the enrichment job BEFORE returning. Best-effort — any
        # failure is logged and swallowed so it can never fail the chat job.
        try:
            await _maybe_trigger_illustration(input_data, graph_result, model_override)
        except Exception as e:
            logger.warning(f"auto-illustrate trigger skipped (swallowed): {e}")

        processing_time = time.time() - start_time
        logger.info(
            f"chat_completion ({input_data.kind}) done for {full_session_id} "
            f"in {processing_time:.2f}s"
        )
        return ChatCompletionOutput(
            success=True,
            session_id=input_data.session_id,
            kind=input_data.kind,
            processing_time=processing_time,
        )

    except Exception as e:
        # Convert raw provider errors into a user-friendly message, then re-raise
        # so surreal-commands marks the job `failed` with that message.
        try:
            _, user_message = classify_error(e)
        except Exception:
            user_message = str(e)
        logger.error(f"chat_completion failed for {full_session_id}: {e}")
        raise RuntimeError(user_message) from e
