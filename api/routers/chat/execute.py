import asyncio
import traceback
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from api.routers._helpers import ensure_prefix, get_or_404
from api.routers.chat.citations import _build_chat_message
from api.routers.chat.schemas import (
    BuildContextRequest,
    BuildContextResponse,
    ChatMessage,
    ExecuteChatRequest,
    ExecuteChatResponse,
)
from open_notebook.domain.notebook import ChatSession, Note, Notebook, Source
from open_notebook.graphs.chat import graph as chat_graph

router = APIRouter()


@router.post("/chat/execute", response_model=ExecuteChatResponse)
async def execute_chat(request: ExecuteChatRequest):
    """Execute a chat request and get AI response."""
    try:
        full_session_id = ensure_prefix(request.session_id, "chat_session")
        session = await get_or_404(ChatSession, full_session_id, "Session")

        notebook = None
        notebook_id = await session.get_notebook_id()
        if notebook_id:
            notebook = await Notebook.get(notebook_id)

        # Per-request override takes precedence over session-level override
        model_override = (
            request.model_override
            if request.model_override is not None
            else getattr(session, "model_override", None)
        )

        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        current_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        state_values = current_state.values if current_state else {}
        state_values["messages"] = state_values.get("messages", [])
        state_values["context"] = request.context
        state_values["notebook"] = notebook
        state_values["model_override"] = model_override
        state_values["quote"] = getattr(session, "quote", None)

        # Media attachments ride on additional_kwargs so they (a) round-trip through
        # the LangGraph checkpoint and (b) reach the model: Esperanto inlines images
        # as multimodal blocks, the agent path references them as files.
        additional_kwargs: Dict[str, Any] = {}
        if request.media:
            additional_kwargs["media"] = [m.model_dump() for m in request.media]
        user_message = HumanMessage(
            content=request.message, additional_kwargs=additional_kwargs
        )
        state_values["messages"].append(user_message)

        result = chat_graph.invoke(
            input=state_values,  # type: ignore[arg-type]
            config=RunnableConfig(
                configurable={
                    "thread_id": full_session_id,
                    "model_id": model_override,
                }
            ),
        )

        await session.save()

        messages: List[ChatMessage] = []
        for msg in result.get("messages", []):
            messages.append(await _build_chat_message(msg, len(messages)))

        return ExecuteChatResponse(session_id=request.session_id, messages=messages)
    except Exception as e:
        logger.error(
            f"Error executing chat: {str(e)}\n"
            f"  Session ID: {request.session_id}\n"
            f"  Model override: {request.model_override}\n"
            f"  Traceback:\n{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail=f"Error executing chat: {str(e)}")


@router.post("/chat/context", response_model=BuildContextResponse)
async def build_context(request: BuildContextRequest):
    """Build context for a notebook based on context configuration."""
    try:
        notebook = await get_or_404(Notebook, request.notebook_id, "Notebook")

        context_data: Dict[str, List[Dict[str, str]]] = {"sources": [], "notes": []}
        total_content = ""

        if request.context_config:
            for source_id, status in request.context_config.get("sources", {}).items():
                if "not in" in status:
                    continue

                try:
                    full_source_id = (
                        source_id
                        if source_id.startswith("source:")
                        else f"source:{source_id}"
                    )

                    try:
                        source = await Source.get(full_source_id)
                    except Exception:
                        continue

                    if "insights" in status:
                        source_context = await source.get_context(context_size="short")
                        context_data["sources"].append(source_context)
                        total_content += str(source_context)
                    elif "full content" in status:
                        source_context = await source.get_context(context_size="long")
                        context_data["sources"].append(source_context)
                        total_content += str(source_context)
                except Exception as e:
                    logger.warning(f"Error processing source {source_id}: {str(e)}")
                    continue

            for note_id, status in request.context_config.get("notes", {}).items():
                if "not in" in status:
                    continue

                try:
                    full_note_id = (
                        note_id if note_id.startswith("note:") else f"note:{note_id}"
                    )
                    note = await Note.get(full_note_id)
                    if not note:
                        continue

                    if "full content" in status:
                        note_context = note.get_context(context_size="long")
                        context_data["notes"].append(note_context)
                        total_content += str(note_context)
                except Exception as e:
                    logger.warning(f"Error processing note {note_id}: {str(e)}")
                    continue
        else:
            sources = await notebook.get_sources()
            for source in sources:
                try:
                    source_context = await source.get_context(context_size="short")
                    context_data["sources"].append(source_context)
                    total_content += str(source_context)
                except Exception as e:
                    logger.warning(f"Error processing source {source.id}: {str(e)}")
                    continue

            notes = await notebook.get_notes()
            for note in notes:
                try:
                    note_context = note.get_context(context_size="short")
                    context_data["notes"].append(note_context)
                    total_content += str(note_context)
                except Exception as e:
                    logger.warning(f"Error processing note {note.id}: {str(e)}")
                    continue

        char_count = len(total_content)
        try:
            from open_notebook.utils import token_count

            estimated_tokens = token_count(total_content) if total_content else 0
        except ImportError:
            estimated_tokens = char_count // 4

        return BuildContextResponse(
            context=context_data, token_count=estimated_tokens, char_count=char_count
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building context: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error building context: {str(e)}")
