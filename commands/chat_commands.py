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
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from commands._heavy_lane import heavy_lane, is_heavy_model
from open_notebook.domain.notebook import ChatSession, Notebook
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.graphs.source_chat import source_chat_graph
from open_notebook.utils.error_classifier import classify_error


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
            state_values["messages"].append(HumanMessage(content=input_data.message))
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

            additional_kwargs = {}
            if input_data.media:
                additional_kwargs["media"] = input_data.media
            state_values["messages"].append(
                HumanMessage(
                    content=input_data.message, additional_kwargs=additional_kwargs
                )
            )

        await _run_graph(graph, state_values, full_session_id, model_override)

        # Touch the session's updated timestamp (mirrors the old endpoint).
        await session.save()

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
