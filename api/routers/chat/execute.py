import json
import traceback
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.command_service import CommandService
from api.routers._helpers import ensure_prefix, get_or_404
from api.routers.chat.schemas import (
    BuildContextRequest,
    BuildContextResponse,
    ExecuteChatJobResponse,
    ExecuteChatRequest,
)
from open_notebook.domain.notebook import ChatSession, Note, Notebook, Source

router = APIRouter()


@router.post("/chat/execute", response_model=ExecuteChatJobResponse, status_code=202)
async def execute_chat(request: ExecuteChatRequest):
    """Submit a chat request to the background worker and return a job ID."""
    try:
        full_session_id = ensure_prefix(request.session_id, "chat_session")
        session = await get_or_404(ChatSession, full_session_id, "Session")

        notebook_id = await session.get_notebook_id()

        # Per-request override takes precedence over session-level override
        model_override = (
            request.model_override
            if request.model_override is not None
            else getattr(session, "model_override", None)
        )

        job_id = await CommandService.submit_command_job(
            "open_notebook",
            "chat_completion",
            {
                "session_id": full_session_id,
                "message": request.message,
                "context": json.dumps(request.context),
                "model_override": model_override,
                "media": [m.model_dump() for m in request.media] if request.media else [],
                "kind": "notebook",
                "notebook_id": notebook_id,
                "label": request.message[:60],
            },
        )

        return ExecuteChatJobResponse(job_id=job_id, session_id=request.session_id)
    except Exception as e:
        logger.error(
            f"Error submitting chat job: {str(e)}\n"
            f"  Session ID: {request.session_id}\n"
            f"  Traceback:\n{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail=f"Error submitting chat job: {str(e)}")


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
