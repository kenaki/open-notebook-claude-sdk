import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path
from langchain_core.runnables import RunnableConfig
from loguru import logger
from pydantic import BaseModel, Field

from api.command_service import CommandService
from api.routers._helpers import ensure_prefix, get_or_404
from open_notebook.database.repository import (
    ensure_record_id,
    repo_query,
    repo_relate,
)
from open_notebook.domain import blocks
from open_notebook.domain.notebook import ChatSession, Source, SourceAnnotation
from open_notebook.exceptions import NotFoundError
from open_notebook.graphs.source_chat import (
    annotation_block_content,
    build_annotation_context_section,
)
from open_notebook.graphs.source_chat import (
    source_chat_graph as source_chat_graph,
)
from open_notebook.utils.graph_utils import get_session_message_count

router = APIRouter()


# Request/Response models
class CreateSourceChatSessionRequest(BaseModel):
    source_id: str = Field(..., description="Source ID to create chat session for")
    title: Optional[str] = Field(None, description="Optional session title")
    model_override: Optional[str] = Field(
        None, description="Optional model override for this session"
    )

class UpdateSourceChatSessionRequest(BaseModel):
    title: Optional[str] = Field(None, description="New session title")
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )

class AnnotationRef(BaseModel):
    """A structured annotation reference attached to a chat message (Chunk D2).

    Surfaced on the session-GET payload so the UI can render reference pills."""

    id: str = Field(..., description="Annotation ID")
    quote: Optional[str] = Field(None, description="Highlighted quote text")
    block_seq: Optional[int] = Field(None, description="Anchored block seq (None if legacy)")
    page: Optional[int] = Field(None, description="1-indexed page of the annotation")


class RecallRef(BaseModel):
    """A structured recall reference — a pointer to a prior chat exchange or
    annotation, surfaced on an AI message (study-memory Track B, chunk B3).

    Matches the coordinator's RecallRef contract exactly (11 fields). Metadata
    only: never carries the exchange gist, the annotation note, or any answer
    text — that's the structural spoiler guard (see domain/recall.py). The
    extra backend-only ``id`` key that ``recall_search`` attaches for
    ``get_past_discussion`` addressing (coordinator decision X-recall-id-key)
    is filtered out before this model is built — it is NOT one of these
    fields and must never become one.
    """

    kind: str = Field(..., description="'exchange' or 'annotation'")
    title: Optional[str] = Field(
        None, description="Session title (exchange) or source title (annotation)"
    )
    session_id: Optional[str] = Field(
        None, description="Full chat_session id (exchange only)"
    )
    scope: Optional[str] = Field(
        None, description="'source' or 'notebook' (exchange only)"
    )
    source_id: Optional[str] = Field(
        None,
        description="Owning source id (annotation always; exchange when scope=source)",
    )
    notebook_id: Optional[str] = Field(
        None, description="Owning notebook id (exchange when scope=notebook)"
    )
    message_id: Optional[str] = Field(
        None, description="AI message id of the prior exchange (unused in v1 UI)"
    )
    annotation_id: Optional[str] = Field(
        None, description="Full source_annotation id (annotation only)"
    )
    page: Optional[int] = Field(None, description="1-indexed page (annotation only)")
    quote: Optional[str] = Field(
        None,
        description="<=200 char snippet: question (exchange) or highlight quote (annotation)",
    )
    similarity: float = Field(..., description="Vector similarity score")


def _parse_recall_refs(extra: Dict[str, Any]) -> Optional[List[RecallRef]]:
    """Parse ``additional_kwargs.recall_refs`` into contract-shaped RecallRef
    models. Filters each raw ref dict down to the known RecallRef fields,
    silently dropping the backend-only ``id`` key (and any other unknown key)
    rather than raising. Absent/empty (older sessions, human turns) -> None."""
    raw_refs = extra.get("recall_refs") if isinstance(extra, dict) else None
    if not raw_refs:
        return None
    return [
        RecallRef(**{k: v for k, v in ref.items() if k in RecallRef.model_fields})
        for ref in raw_refs
    ]


class ChatMessage(BaseModel):
    id: str = Field(..., description="Message ID")
    type: str = Field(..., description="Message type (human|ai)")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(None, description="Message timestamp")
    annotation_refs: Optional[List[AnnotationRef]] = Field(
        None, description="Structured annotation references carried by this message"
    )
    thinking: Optional[str] = Field(
        None, description="Extracted <think> reasoning, if the model produced any"
    )
    recall_refs: Optional[List[RecallRef]] = Field(
        None,
        description="Structured recall references (past discussions/highlights) carried by this message",
    )


class ContextIndicator(BaseModel):
    sources: List[str] = Field(
        default_factory=list, description="Source IDs used in context"
    )
    insights: List[str] = Field(
        default_factory=list, description="Insight IDs used in context"
    )
    notes: List[str] = Field(
        default_factory=list, description="Note IDs used in context"
    )

class SourceChatSessionResponse(BaseModel):
    id: str = Field(..., description="Session ID")
    title: str = Field(..., description="Session title")
    source_id: str = Field(..., description="Source ID")
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )
    created: str = Field(..., description="Creation timestamp")
    updated: str = Field(..., description="Last update timestamp")
    message_count: Optional[int] = Field(
        None, description="Number of messages in session"
    )

class SourceChatSessionWithMessagesResponse(SourceChatSessionResponse):
    messages: List[ChatMessage] = Field(
        default_factory=list, description="Session messages"
    )
    context_indicators: Optional[ContextIndicator] = Field(
        None, description="Context indicators from last response"
    )

class SendMessageRequest(BaseModel):
    message: str = Field(..., description="User message content")
    model_override: Optional[str] = Field(
        None, description="Optional model override for this message"
    )
    annotation_ids: List[str] = Field(
        default_factory=list,
        description=(
            "Annotation IDs the user is referencing; each is resolved into the "
            "AI context and recorded as a cites_annotation edge (Chunk D2)."
        ),
    )

class SuccessResponse(BaseModel):
    success: bool = Field(True, description="Operation success status")
    message: str = Field(..., description="Success message")


class SendSourceChatJobResponse(BaseModel):
    job_id: str = Field(..., description="Background job ID")
    session_id: str = Field(..., description="Chat session ID")


# Cap referenced annotations per message so a tag-ask over a large tag can't blow
# the agent context (Track D Open Question Q-tag-ask-limit; default 10).
_MAX_ANNOTATION_REFS = 10


async def _relate_citation(full_session_id: str, annotation_id: str) -> None:
    """Record a ``chat_session->cites_annotation->source_annotation`` edge once.

    SELECT-checks first so re-referencing the same annotation across turns does
    not pile up duplicate edges (db-design §2.4 / §3b)."""
    existing = await repo_query(
        "SELECT id FROM cites_annotation WHERE in = $s AND out = $a LIMIT 1",
        {"s": ensure_record_id(full_session_id), "a": ensure_record_id(annotation_id)},
    )
    if not existing:
        await repo_relate(full_session_id, "cites_annotation", annotation_id)


async def _resolve_annotations_for_chat(
    source: Source, full_session_id: str, annotation_ids: List[str]
) -> tuple[str, List[dict]]:
    """Resolve referenced annotations into (context_section, annotation_refs).

    For each annotation that belongs to ``source`` (invalid/foreign ids are
    skipped, not fatal): records the ``cites_annotation`` edge, then — if the
    annotation is block-anchored — fetches its block window (radius 3, one round
    trip, db-design §3b) and renders the anchored block's content; otherwise falls
    back to the stored quote + page. Returns the structured context block for the
    prompt and a compact refs list for the UI pills.
    """
    src_id = str(source.id)
    src_key = src_id.split(":", 1)[1] if ":" in src_id else src_id
    parse_gen = source.parse_generation

    resolved: List[dict] = []
    refs: List[dict] = []
    for raw_id in annotation_ids[:_MAX_ANNOTATION_REFS]:
        annotation_id = ensure_prefix(raw_id, "source_annotation")
        try:
            annotation = await SourceAnnotation.get(annotation_id)
        except NotFoundError:
            logger.warning(f"Skipping unknown annotation ref {annotation_id}")
            continue
        if str(annotation.source) != src_id:
            logger.warning(
                f"Skipping annotation {annotation_id}: not part of source {src_id}"
            )
            continue

        await _relate_citation(full_session_id, annotation_id)

        item = {
            "section_path": [],
            "content": annotation.quote or "",
            "note": annotation.note,
        }
        if annotation.block_seq is not None and parse_gen is not None:
            gen = annotation.anchor_gen if annotation.anchor_gen is not None else parse_gen
            window = await blocks.get_window(
                src_key, gen, annotation.block_seq, radius=3
            )
            block = next(
                (b for b in window if b.get("seq") == annotation.block_seq), None
            )
            if block:
                item["section_path"] = block.get("section_path") or []
                item["content"] = annotation_block_content(block, annotation.quote)
        resolved.append(item)
        refs.append(
            {
                "id": annotation.id,
                "quote": annotation.quote,
                "block_seq": annotation.block_seq,
                "page": annotation.page,
            }
        )

    return build_annotation_context_section(resolved), refs


@router.post(
    "/sources/{source_id}/chat/sessions", response_model=SourceChatSessionResponse
)
async def create_source_chat_session(
    request: CreateSourceChatSessionRequest,
    source_id: str = Path(..., description="Source ID"),
):
    """Create a new chat session for a source."""
    try:
        # Verify source exists
        full_source_id = ensure_prefix(source_id, "source")
        source = await get_or_404(Source, full_source_id, "Source")

        # Create new session with model_override support
        session = ChatSession(
            title=request.title or f"Source Chat {asyncio.get_event_loop().time():.0f}",
            model_override=request.model_override,
        )
        await session.save()

        # Relate session to source using "refers_to" relation
        await session.relate("refers_to", full_source_id)

        return SourceChatSessionResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            source_id=source_id,
            model_override=session.model_override,
            created=str(session.created),
            updated=str(session.updated),
            message_count=0,
        )
    except Exception as e:
        logger.error(f"Error creating source chat session: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating source chat session: {str(e)}"
        )


@router.get(
    "/sources/{source_id}/chat/sessions", response_model=List[SourceChatSessionResponse]
)
async def get_source_chat_sessions(source_id: str = Path(..., description="Source ID")):
    """Get all chat sessions for a source."""
    try:
        # Verify source exists
        full_source_id = ensure_prefix(source_id, "source")
        source = await get_or_404(Source, full_source_id, "Source")

        # Get sessions that refer to this source - first get relations, then
        # fetch ALL session rows in ONE query (was an N+1 SELECT-per-session).
        # The per-session checkpoint reads below stay (cheap local SQLite).
        session_ids = await ChatSession.get_ids_for_source(full_source_id)
        rid_list = [ensure_record_id(str(sid)) for sid in session_ids if sid]

        session_rows = []
        if rid_list:
            session_rows = await repo_query(
                "SELECT * FROM chat_session WHERE id IN $ids", {"ids": rid_list}
            )

        sessions = []
        for session_data in session_rows:
            session_id = str(session_data.get("id"))

            # Get message count from LangGraph state (per-session checkpoint load)
            msg_count = await get_session_message_count(
                source_chat_graph, session_id
            )

            sessions.append(
                SourceChatSessionResponse(
                    id=session_data.get("id") or "",
                    title=session_data.get("title") or "Untitled Session",
                    source_id=source_id,
                    model_override=session_data.get("model_override"),
                    created=str(session_data.get("created")),
                    updated=str(session_data.get("updated")),
                    message_count=msg_count,
                )
            )

        # Sort sessions by created date (newest first)
        sessions.sort(key=lambda x: x.created, reverse=True)
        return sessions
    except Exception as e:
        logger.error(f"Error fetching source chat sessions: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching source chat sessions: {str(e)}"
        )


@router.get(
    "/sources/{source_id}/chat/sessions/{session_id}",
    response_model=SourceChatSessionWithMessagesResponse,
)
async def get_source_chat_session(
    source_id: str = Path(..., description="Source ID"),
    session_id: str = Path(..., description="Session ID"),
):
    """Get a specific source chat session with its messages."""
    try:
        # Verify source exists
        full_source_id = ensure_prefix(source_id, "source")
        source = await get_or_404(Source, full_source_id, "Source")

        # Get session
        full_session_id = ensure_prefix(session_id, "chat_session")
        session = await get_or_404(ChatSession, full_session_id, "Session")

        # Verify session is related to this source
        linked_session_ids = await ChatSession.get_ids_for_source(full_source_id)
        if not any(str(sid) == full_session_id for sid in linked_session_ids):
            raise HTTPException(
                status_code=404, detail="Session not found for this source"
            )

        # Get session state from LangGraph to retrieve messages
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        thread_state = await asyncio.to_thread(
            source_chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        # Extract messages from state
        messages: list[ChatMessage] = []
        context_indicators = None

        if thread_state and thread_state.values:
            # Extract messages
            if "messages" in thread_state.values:
                for msg in thread_state.values["messages"]:
                    # Structured annotation references (Chunk D2) ride in the
                    # human message's additional_kwargs; surface them for pills.
                    extra = getattr(msg, "additional_kwargs", None) or {}
                    raw_refs = extra.get("annotation_refs")
                    annotation_refs = (
                        [AnnotationRef(**ref) for ref in raw_refs]
                        if raw_refs
                        else None
                    )
                    # Post-hoc thinking (A2): persisted by the graph node when
                    # the model emitted <think> content; absent on messages
                    # checkpointed before this change — degrade to None.
                    raw_thinking = extra.get("thinking")
                    thinking = (
                        raw_thinking
                        if isinstance(raw_thinking, str) and raw_thinking
                        else None
                    )
                    # Structured recall references (study-memory, chunk B3):
                    # ride in the AI message's additional_kwargs, same seam as
                    # tool_uses/annotation_refs/thinking; absent on human turns
                    # and on messages checkpointed before this change.
                    recall_refs = _parse_recall_refs(extra)
                    messages.append(
                        ChatMessage(
                            id=getattr(msg, "id", f"msg_{len(messages)}"),
                            type=msg.type if hasattr(msg, "type") else "unknown",
                            content=msg.content
                            if hasattr(msg, "content")
                            else str(msg),
                            timestamp=None,  # LangChain messages don't have timestamps by default
                            annotation_refs=annotation_refs,
                            thinking=thinking,
                            recall_refs=recall_refs,
                        )
                    )

            # Extract context indicators from the last state
            if "context_indicators" in thread_state.values:
                context_data = thread_state.values["context_indicators"]
                context_indicators = ContextIndicator(
                    sources=context_data.get("sources", []),
                    insights=context_data.get("insights", []),
                    notes=context_data.get("notes", []),
                )

        return SourceChatSessionWithMessagesResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            source_id=source_id,
            model_override=getattr(session, "model_override", None),
            created=str(session.created),
            updated=str(session.updated),
            message_count=len(messages),
            messages=messages,
            context_indicators=context_indicators,
        )
    except Exception as e:
        logger.error(f"Error fetching source chat session: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching source chat session: {str(e)}"
        )


@router.put(
    "/sources/{source_id}/chat/sessions/{session_id}",
    response_model=SourceChatSessionResponse,
)
async def update_source_chat_session(
    request: UpdateSourceChatSessionRequest,
    source_id: str = Path(..., description="Source ID"),
    session_id: str = Path(..., description="Session ID"),
):
    """Update source chat session title and/or model override."""
    try:
        # Verify source exists
        full_source_id = ensure_prefix(source_id, "source")
        source = await get_or_404(Source, full_source_id, "Source")

        # Get session
        full_session_id = ensure_prefix(session_id, "chat_session")
        session = await get_or_404(ChatSession, full_session_id, "Session")

        # Verify session is related to this source
        linked_session_ids = await ChatSession.get_ids_for_source(full_source_id)
        if not any(str(sid) == full_session_id for sid in linked_session_ids):
            raise HTTPException(
                status_code=404, detail="Session not found for this source"
            )

        # Update session fields
        if request.title is not None:
            session.title = request.title
        if request.model_override is not None:
            session.model_override = request.model_override

        await session.save()

        # Get message count from LangGraph state
        msg_count = await get_session_message_count(source_chat_graph, full_session_id)

        return SourceChatSessionResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            source_id=source_id,
            model_override=getattr(session, "model_override", None),
            created=str(session.created),
            updated=str(session.updated),
            message_count=msg_count,
        )
    except Exception as e:
        logger.error(f"Error updating source chat session: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error updating source chat session: {str(e)}"
        )


@router.delete(
    "/sources/{source_id}/chat/sessions/{session_id}", response_model=SuccessResponse
)
async def delete_source_chat_session(
    source_id: str = Path(..., description="Source ID"),
    session_id: str = Path(..., description="Session ID"),
):
    """Delete a source chat session."""
    try:
        # Verify source exists
        full_source_id = ensure_prefix(source_id, "source")
        source = await get_or_404(Source, full_source_id, "Source")

        # Get session
        full_session_id = ensure_prefix(session_id, "chat_session")
        session = await get_or_404(ChatSession, full_session_id, "Session")

        # Verify session is related to this source
        linked_session_ids = await ChatSession.get_ids_for_source(full_source_id)
        if not any(str(sid) == full_session_id for sid in linked_session_ids):
            raise HTTPException(
                status_code=404, detail="Session not found for this source"
            )

        await session.delete()

        return SuccessResponse(
            success=True, message="Source chat session deleted successfully"
        )
    except Exception as e:
        logger.error(f"Error deleting source chat session: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error deleting source chat session: {str(e)}"
        )


@router.post(
    "/sources/{source_id}/chat/sessions/{session_id}/messages",
    response_model=SendSourceChatJobResponse,
    status_code=202,
)
async def send_message_to_source_chat(
    request: SendMessageRequest,
    source_id: str = Path(..., description="Source ID"),
    session_id: str = Path(..., description="Session ID"),
):
    """Submit a source-chat message to the background worker; returns job_id + session_id."""
    try:
        # Verify source exists (need the full record for parse_generation below)
        full_source_id = ensure_prefix(source_id, "source")
        source = await get_or_404(Source, full_source_id, "Source")

        # Verify session exists and is related to source
        full_session_id = ensure_prefix(session_id, "chat_session")
        session = await get_or_404(ChatSession, full_session_id, "Session")

        # Verify session is related to this source
        linked_session_ids = await ChatSession.get_ids_for_source(full_source_id)
        if not any(str(sid) == full_session_id for sid in linked_session_ids):
            raise HTTPException(
                status_code=404, detail="Session not found for this source"
            )

        if not request.message:
            raise HTTPException(status_code=400, detail="Message content is required")

        # Determine model override (request override takes precedence over session override)
        model_override = request.model_override or getattr(
            session, "model_override", None
        )

        # Resolve any structured annotation references (Chunk D2): records the
        # cites_annotation edges and builds the AI-context section + refs. Both
        # travel to the worker as typed fields on the command input (not embedded
        # in message content), which the chat_completion source branch forwards
        # into graph state / the human message's additional_kwargs.
        annotation_ctx = ""
        annotation_refs: List[dict] = []
        if request.annotation_ids:
            annotation_ctx, annotation_refs = await _resolve_annotations_for_chat(
                source, full_session_id, request.annotation_ids
            )

        job_id = await CommandService.submit_command_job(
            "open_notebook",
            "chat_completion",
            {
                "session_id": full_session_id,
                "message": request.message,
                "model_override": model_override,
                "kind": "source",
                "source_id": full_source_id,
                "label": request.message[:60],
                "annotation_context": annotation_ctx,
                "annotation_refs": annotation_refs,
            },
        )

        return SendSourceChatJobResponse(job_id=job_id, session_id=full_session_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting source chat job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error submitting source chat job: {str(e)}")
