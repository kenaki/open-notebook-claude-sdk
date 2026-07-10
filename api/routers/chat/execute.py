import json
import traceback

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.annotation_refs import (
    make_cached_source_resolver,
    make_source_in_notebook_check,
    resolve_annotations_for_chat,
)
from api.command_service import CommandService
from api.context_service import build_context_data
from api.routers._helpers import ensure_prefix, get_or_404
from api.routers.chat.schemas import (
    BuildContextRequest,
    BuildContextResponse,
    ExecuteChatJobResponse,
    ExecuteChatRequest,
)
from open_notebook.domain.notebook import ChatSession, Notebook

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

        # Resolve any referenced annotations BEFORE job submit (mirrors the
        # source-chat send path): records the cites_annotation edges and builds
        # the REFERENCED-ANNOTATION prompt section + the compact refs list. Both
        # travel to the worker as typed ChatCompletionInput fields, not embedded
        # in message content. Ownership = the annotation's source belongs to this
        # notebook (reference edge); refs may span sources, so each is fetched.
        annotation_ctx = ""
        annotation_refs: list = []
        if request.annotation_ids and notebook_id:
            annotation_ctx, annotation_refs = await resolve_annotations_for_chat(
                request.annotation_ids,
                full_session_id,
                check_ownership=make_source_in_notebook_check(notebook_id),
                resolve_source=make_cached_source_resolver(),
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
                "annotation_context": annotation_ctx,
                "annotation_refs": annotation_refs,
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

        # Empty config → default (all sources/notes), matching the original
        # `if request.context_config:` truthiness check.
        sources_ctx, notes_ctx, total_content = await build_context_data(
            notebook, request.context_config or None
        )
        context_data = {"sources": sources_ctx, "notes": notes_ctx}

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
