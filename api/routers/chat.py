import asyncio
import os
import re
import traceback
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from langchain_core.runnables import RunnableConfig
from loguru import logger
from pydantic import BaseModel, Field

from api.upload_utils import resolve_within, save_uploaded_file
from open_notebook.config import CHAT_MEDIA_FOLDER
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import (
    ChatSession,
    Note,
    Notebook,
    Source,
    SourceInsight,
)
from open_notebook.exceptions import (
    NotFoundError,
)
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.utils.graph_utils import get_session_message_count

router = APIRouter()


# Request/Response models
class CreateSessionRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID to create session for")
    title: Optional[str] = Field(None, description="Optional session title")
    model_override: Optional[str] = Field(
        None, description="Optional model override for this session"
    )
    parent_session_id: Optional[str] = Field(
        None, description="Parent session ID if this is a sub-chat"
    )
    quote: Optional[str] = Field(
        None, description="Highlighted passage that seeded this sub-chat"
    )
    tags: Optional[List[str]] = Field(
        None, description="Grouping tags to assign to this session"
    )


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = Field(None, description="New session title")
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )
    parent_session_id: Optional[str] = Field(
        None, description="Parent session ID if this is a sub-chat"
    )
    quote: Optional[str] = Field(
        None, description="Highlighted passage that seeded this sub-chat"
    )
    tags: Optional[List[str]] = Field(
        None, description="Grouping tags for this session (replaces existing)"
    )


class Citation(BaseModel):
    id: str = Field(..., description="Full document id including type prefix")
    type: Literal["source", "note", "source_insight"] = Field(
        ..., description="Cited document type"
    )
    number: int = Field(..., description="First-appearance citation number")
    title: Optional[str] = Field(None, description="Resolved document title")
    snippet: Optional[str] = Field(None, description="Short content excerpt")
    page: Optional[int] = Field(
        None, description="Optional page anchor (pdf-viewer-citations hook)"
    )


class ToolUseDisclosure(BaseModel):
    id: str = Field(..., description="Tool-use block id from the agent run")
    tool_name: str = Field(
        ..., description="Raw MCP tool name (e.g. mcp__open_notebook__search)"
    )
    tool_input: Dict[str, Any] = Field(
        default_factory=dict, description="Arguments the agent passed to the tool"
    )
    tool_result: Optional[str] = Field(
        None, description="Stringified tool result, if captured"
    )
    is_error: Optional[bool] = Field(
        None, description="Whether the tool reported an error"
    )


class MediaItem(BaseModel):
    type: Literal["image", "video"] = Field(..., description="Attachment kind")
    url: str = Field(..., description="Fetchable URL served by GET /chat/media/{file}")
    label: str = Field(..., description="Display label (original filename)")
    duration: Optional[str] = Field(
        None, description="Optional media duration (e.g. video length)"
    )


class ChatMessage(BaseModel):
    id: str = Field(..., description="Message ID")
    type: str = Field(..., description="Message type (human|ai)")
    content: str = Field(..., description="Message content")
    timestamp: Optional[str] = Field(None, description="Message timestamp")
    citations: List[Citation] = Field(
        default_factory=list, description="Resolved citation markers in this message"
    )
    followups: List[str] = Field(
        default_factory=list, description="Suggested follow-up questions"
    )
    tool_uses: Optional[List[ToolUseDisclosure]] = Field(
        None, description="MCP tools the Claude Agent invoked for this message"
    )
    media: List[MediaItem] = Field(
        default_factory=list, description="Image/video attachments on this message"
    )


class ChatSessionResponse(BaseModel):
    id: str = Field(..., description="Session ID")
    title: str = Field(..., description="Session title")
    notebook_id: Optional[str] = Field(None, description="Notebook ID")
    created: str = Field(..., description="Creation timestamp")
    updated: str = Field(..., description="Last update timestamp")
    message_count: Optional[int] = Field(
        None, description="Number of messages in session"
    )
    model_override: Optional[str] = Field(
        None, description="Model override for this session"
    )
    parent_session_id: Optional[str] = Field(
        None, description="Parent session ID if this is a sub-chat"
    )
    quote: Optional[str] = Field(
        None, description="Highlighted passage that seeded this sub-chat"
    )
    tags: List[str] = Field(
        default_factory=list, description="Grouping tags assigned to this session"
    )


class ChatSessionWithMessagesResponse(ChatSessionResponse):
    messages: List[ChatMessage] = Field(
        default_factory=list, description="Session messages"
    )


class ExecuteChatRequest(BaseModel):
    session_id: str = Field(..., description="Chat session ID")
    message: str = Field(..., description="User message content")
    context: Dict[str, Any] = Field(
        ..., description="Chat context with sources and notes"
    )
    model_override: Optional[str] = Field(
        None, description="Optional model override for this message"
    )
    media: List[MediaItem] = Field(
        default_factory=list, description="Image/video attachments for this message"
    )


class ExecuteChatResponse(BaseModel):
    session_id: str = Field(..., description="Session ID")
    messages: List[ChatMessage] = Field(..., description="Updated message list")


class BuildContextRequest(BaseModel):
    notebook_id: str = Field(..., description="Notebook ID")
    context_config: Dict[str, Any] = Field(..., description="Context configuration")


class BuildContextResponse(BaseModel):
    context: Dict[str, Any] = Field(..., description="Built context data")
    token_count: int = Field(..., description="Estimated token count")
    char_count: int = Field(..., description="Character count")


class SuccessResponse(BaseModel):
    success: bool = Field(True, description="Operation success status")
    message: str = Field(..., description="Success message")


# Citation / followups resolution ------------------------------------------------

# Inline marker form: [source:id] / [note:id] / [source_insight:id], tolerating an
# optional #p=<n> page anchor (see pdf-viewer-citations plan). The literal type
# prefix matches the actual SurrealDB record ids returned by the search tool.
FOLLOWUPS_SENTINEL = "---FOLLOWUPS---"
_CITATION_PATTERN = re.compile(
    r"(source_insight|note|source):([a-zA-Z0-9_]+)(?:#p=(\d+))?"
)
_BULLET_PATTERN = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _make_snippet(text: Optional[str], limit: int = 160) -> Optional[str]:
    """Collapse whitespace and clip to a short preview snippet."""
    if not text:
        return None
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


async def _fetch_citation_meta(
    ctype: str, full_id: str
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a (title, snippet) pair for a cited document, defensively."""
    try:
        if ctype == "source":
            src = await Source.get(full_id)
            if src:
                return src.title, _make_snippet(getattr(src, "full_text", None))
        elif ctype == "note":
            note = await Note.get(full_id)
            if note:
                return note.title, _make_snippet(getattr(note, "content", None))
        elif ctype == "source_insight":
            insight = await SourceInsight.get(full_id)
            if insight:
                return (
                    getattr(insight, "insight_type", None),
                    _make_snippet(getattr(insight, "content", None)),
                )
    except Exception as e:
        logger.warning(f"Could not resolve citation {full_id}: {str(e)}")
    return None, None


async def _resolve_citations(
    content: str,
) -> Tuple[str, List[Citation], List[str]]:
    """Parse inline citation markers + a trailing ---FOLLOWUPS--- block.

    Returns (clean_content, citations, followups). Inline markers are KEPT in
    clean_content for frontend back-compat; only the followups block is stripped.
    Citations are deduplicated and numbered by first appearance.
    """
    if not content:
        return content, [], []

    # Split off the followups block (everything after the sentinel)
    clean = content
    followups: List[str] = []
    if FOLLOWUPS_SENTINEL in content:
        head, _, tail = content.partition(FOLLOWUPS_SENTINEL)
        clean = head.rstrip()
        for line in tail.splitlines():
            stripped = _BULLET_PATTERN.sub("", line).strip()
            if stripped:
                followups.append(stripped)

    # Extract + number citations by first appearance (dedup on full id)
    citations: List[Citation] = []
    seen: Dict[str, int] = {}
    for match in _CITATION_PATTERN.finditer(clean):
        ctype, cid, page = match.group(1), match.group(2), match.group(3)
        full_id = f"{ctype}:{cid}"
        if full_id in seen:
            continue
        number = len(seen) + 1
        seen[full_id] = number
        title, snippet = await _fetch_citation_meta(ctype, full_id)
        citations.append(
            Citation(
                id=full_id,
                type=ctype,  # type: ignore[arg-type]
                number=number,
                title=title,
                snippet=snippet,
                page=int(page) if page else None,
            )
        )

    return clean, citations, followups


async def _build_chat_message(msg: Any, fallback_index: int) -> ChatMessage:
    """Convert a LangChain message into a ChatMessage, resolving AI citations."""
    mtype = msg.type if hasattr(msg, "type") else "unknown"
    mcontent = msg.content if hasattr(msg, "content") else str(msg)

    if mtype == "ai" and isinstance(mcontent, str):
        clean, citations, followups = await _resolve_citations(mcontent)
    else:
        clean = mcontent if isinstance(mcontent, str) else str(mcontent)
        citations, followups = [], []

    # Tool-use disclosures + media attachments ride on the message's
    # additional_kwargs (tool_uses: Claude Agent path / AI only; media: the human
    # turn). Absent/empty on the other paths.
    extra = getattr(msg, "additional_kwargs", None) or {}
    raw_tool_uses = extra.get("tool_uses") if isinstance(extra, dict) else None
    tool_uses = (
        [ToolUseDisclosure(**t) for t in raw_tool_uses] if raw_tool_uses else None
    )
    raw_media = extra.get("media") if isinstance(extra, dict) else None
    media = [MediaItem(**m) for m in raw_media] if raw_media else []

    return ChatMessage(
        id=getattr(msg, "id", f"msg_{fallback_index}"),
        type=mtype,
        content=clean,
        timestamp=None,
        citations=citations,
        followups=followups,
        tool_uses=tool_uses,
        media=media,
    )


@router.get("/chat/sessions", response_model=List[ChatSessionResponse])
async def get_sessions(notebook_id: str = Query(..., description="Notebook ID")):
    """Get all chat sessions for a notebook."""
    try:
        # Get notebook to verify it exists
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # Get sessions for this notebook
        sessions_list = await notebook.get_chat_sessions()

        results = []
        for session in sessions_list:
            session_id = str(session.id)

            # Get message count from LangGraph state
            msg_count = await get_session_message_count(chat_graph, session_id)

            results.append(
                ChatSessionResponse(
                    id=session.id or "",
                    title=session.title or "Untitled Session",
                    notebook_id=notebook_id,
                    created=str(session.created),
                    updated=str(session.updated),
                    message_count=msg_count,
                    model_override=getattr(session, "model_override", None),
                    parent_session_id=getattr(session, "parent_session_id", None),
                    quote=getattr(session, "quote", None),
                    tags=getattr(session, "tags", []) or [],
                )
            )

        return results
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error fetching chat sessions: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching chat sessions: {str(e)}"
        )


@router.post("/chat/sessions", response_model=ChatSessionResponse)
async def create_session(request: CreateSessionRequest):
    """Create a new chat session."""
    try:
        # Verify notebook exists
        notebook = await Notebook.get(request.notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # Create new session
        session = ChatSession(
            title=request.title
            or f"Chat Session {asyncio.get_event_loop().time():.0f}",
            model_override=request.model_override,
            parent_session_id=request.parent_session_id,
            quote=request.quote,
            tags=request.tags or [],
        )
        await session.save()

        # Relate session to notebook
        await session.relate_to_notebook(request.notebook_id)

        return ChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            notebook_id=request.notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=0,
            model_override=session.model_override,
            parent_session_id=session.parent_session_id,
            quote=session.quote,
            tags=session.tags or [],
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    except Exception as e:
        logger.error(f"Error creating chat session: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating chat session: {str(e)}"
        )


@router.get(
    "/chat/sessions/{session_id}", response_model=ChatSessionWithMessagesResponse
)
async def get_session(session_id: str):
    """Get a specific session with its messages."""
    try:
        # Get session
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Get session state from LangGraph to retrieve messages
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        thread_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        # Extract messages from state
        messages: list[ChatMessage] = []
        if thread_state and thread_state.values and "messages" in thread_state.values:
            for msg in thread_state.values["messages"]:
                messages.append(await _build_chat_message(msg, len(messages)))

        # Find notebook_id (we need to query the relationship)
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )

        notebook_query = await repo_query(
            "SELECT out FROM refers_to WHERE in = $session_id",
            {"session_id": ensure_record_id(full_session_id)},
        )

        notebook_id = notebook_query[0]["out"] if notebook_query else None

        if not notebook_id:
            # This might be an old session created before API migration
            logger.warning(
                f"No notebook relationship found for session {session_id} - may be an orphaned session"
            )

        return ChatSessionWithMessagesResponse(
            id=session.id or "",
            title=session.title or "Untitled Session",
            notebook_id=notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=len(messages),
            messages=messages,
            model_override=getattr(session, "model_override", None),
            parent_session_id=getattr(session, "parent_session_id", None),
            quote=getattr(session, "quote", None),
            tags=getattr(session, "tags", []) or [],
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error fetching session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching session: {str(e)}")


@router.put("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(session_id: str, request: UpdateSessionRequest):
    """Update session title."""
    try:
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        update_data = request.model_dump(exclude_unset=True)

        if "title" in update_data:
            session.title = update_data["title"]

        if "model_override" in update_data:
            session.model_override = update_data["model_override"]

        if "parent_session_id" in update_data:
            session.parent_session_id = update_data["parent_session_id"]

        if "quote" in update_data:
            session.quote = update_data["quote"]

        if "tags" in update_data:
            session.tags = update_data["tags"] or []

        await session.save()

        # Find notebook_id
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        notebook_query = await repo_query(
            "SELECT out FROM refers_to WHERE in = $session_id",
            {"session_id": ensure_record_id(full_session_id)},
        )
        notebook_id = notebook_query[0]["out"] if notebook_query else None

        # Get message count from LangGraph state
        msg_count = await get_session_message_count(chat_graph, full_session_id)

        return ChatSessionResponse(
            id=session.id or "",
            title=session.title or "",
            notebook_id=notebook_id,
            created=str(session.created),
            updated=str(session.updated),
            message_count=msg_count,
            model_override=session.model_override,
            parent_session_id=getattr(session, "parent_session_id", None),
            quote=getattr(session, "quote", None),
            tags=getattr(session, "tags", []) or [],
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error updating session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating session: {str(e)}")


@router.delete("/chat/sessions/{session_id}", response_model=SuccessResponse)
async def delete_session(session_id: str):
    """Delete a chat session."""
    try:
        # Ensure session_id has proper table prefix
        full_session_id = (
            session_id
            if session_id.startswith("chat_session:")
            else f"chat_session:{session_id}"
        )
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        await session.delete()

        return SuccessResponse(success=True, message="Session deleted successfully")
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting session: {str(e)}")


@router.post("/chat/execute", response_model=ExecuteChatResponse)
async def execute_chat(request: ExecuteChatRequest):
    """Execute a chat request and get AI response."""
    try:
        # Verify session exists
        # Ensure session_id has proper table prefix
        full_session_id = (
            request.session_id
            if request.session_id.startswith("chat_session:")
            else f"chat_session:{request.session_id}"
        )
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Fetch notebook linked to this session
        notebook_query = await repo_query(
            "SELECT out FROM refers_to WHERE in = $session_id",
            {"session_id": ensure_record_id(full_session_id)},
        )
        notebook = None
        if notebook_query:
            notebook = await Notebook.get(notebook_query[0]["out"])

        # Determine model override (per-request override takes precedence over session-level)
        model_override = (
            request.model_override
            if request.model_override is not None
            else getattr(session, "model_override", None)
        )

        # Get current state
        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        current_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        # Prepare state for execution
        state_values = current_state.values if current_state else {}
        state_values["messages"] = state_values.get("messages", [])
        state_values["context"] = request.context
        state_values["notebook"] = notebook
        state_values["model_override"] = model_override
        state_values["quote"] = getattr(session, "quote", None)

        # Add user message to state. Media attachments ride on additional_kwargs
        # so they (a) round-trip through the LangGraph checkpoint and (b) reach the
        # model: the Esperanto path inlines images as multimodal blocks, the agent
        # path references them as files (see graphs/chat.py + claude_agent.py).
        from langchain_core.messages import HumanMessage

        additional_kwargs = {}
        if request.media:
            additional_kwargs["media"] = [m.model_dump() for m in request.media]
        user_message = HumanMessage(
            content=request.message, additional_kwargs=additional_kwargs
        )
        state_values["messages"].append(user_message)

        # Execute chat graph
        result = chat_graph.invoke(
            input=state_values,  # type: ignore[arg-type]
            config=RunnableConfig(
                configurable={
                    "thread_id": full_session_id,
                    "model_id": model_override,
                }
            ),
        )

        # Update session timestamp
        await session.save()

        # Convert messages to response format
        messages: list[ChatMessage] = []
        for msg in result.get("messages", []):
            messages.append(await _build_chat_message(msg, len(messages)))

        return ExecuteChatResponse(session_id=request.session_id, messages=messages)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        # Log detailed error with context for debugging
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
        # Verify notebook exists
        notebook = await Notebook.get(request.notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        context_data: dict[str, list[dict[str, str]]] = {"sources": [], "notes": []}
        total_content = ""

        # Process context configuration if provided
        if request.context_config:
            # Process sources
            for source_id, status in request.context_config.get("sources", {}).items():
                if "not in" in status:
                    continue

                try:
                    # Add table prefix if not present
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

            # Process notes
            for note_id, status in request.context_config.get("notes", {}).items():
                if "not in" in status:
                    continue

                try:
                    # Add table prefix if not present
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
            # Default behavior - include all sources and notes with short context
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

        # Calculate character and token counts
        char_count = len(total_content)
        # Use token count utility if available
        try:
            from open_notebook.utils import token_count

            estimated_tokens = token_count(total_content) if total_content else 0
        except ImportError:
            # Fallback to simple estimation
            estimated_tokens = char_count // 4

        return BuildContextResponse(
            context=context_data, token_count=estimated_tokens, char_count=char_count
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building context: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error building context: {str(e)}")


# Media attachments ---------------------------------------------------------------


def _classify_media(content_type: Optional[str]) -> Literal["image", "video"]:
    """Map an upload's MIME type to the MediaItem kind (image|video)."""
    ctype = (content_type or "").lower()
    if ctype.startswith("video/"):
        return "video"
    if ctype.startswith("image/"):
        return "image"
    raise HTTPException(
        status_code=400,
        detail="Unsupported media type: only image/* and video/* are accepted",
    )


@router.post("/chat/media", response_model=MediaItem)
async def upload_chat_media(file: UploadFile = File(...)):
    """Upload an image/video to attach to a chat message.

    Stored as a standalone file under ``data/uploads/chat-media/`` (no DB record in
    v1 — see coordinator Q-mediastore). Returns the MediaItem the composer attaches
    to the next ``POST /chat/execute`` call.
    """
    media_type = _classify_media(file.content_type)
    try:
        saved_path = await save_uploaded_file(file, CHAT_MEDIA_FOLDER)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error saving chat media: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error saving chat media: {str(e)}")

    filename = os.path.basename(saved_path)
    return MediaItem(
        type=media_type,
        url=f"/api/chat/media/{filename}",
        label=file.filename or filename,
        duration=None,
    )


@router.get("/chat/media/{filename}")
async def get_chat_media(filename: str):
    """Serve a previously uploaded chat-media file (path-traversal guarded)."""
    try:
        resolved_path = resolve_within(CHAT_MEDIA_FOLDER, filename)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access to file denied")

    if not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="Media not found")

    return FileResponse(
        path=resolved_path, filename=os.path.basename(resolved_path)
    )
