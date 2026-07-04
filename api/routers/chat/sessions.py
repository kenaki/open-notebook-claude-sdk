import asyncio
from typing import List

from fastapi import APIRouter, HTTPException, Query
from langchain_core.runnables import RunnableConfig
from loguru import logger

from api.routers._helpers import ensure_prefix, get_or_404, session_to_response
from api.routers.chat.citations import _build_chat_message
from api.routers.chat.schemas import (
    ChatMessage,
    ChatSessionResponse,
    ChatSessionWithMessagesResponse,
    CreateSessionRequest,
    SuccessResponse,
    UpdateSessionRequest,
)
from open_notebook.domain.notebook import ChatSession, Notebook
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.utils.graph_utils import get_session_message_count

router = APIRouter()


@router.get("/chat/sessions", response_model=List[ChatSessionResponse])
async def get_sessions(notebook_id: str = Query(..., description="Notebook ID")):
    """Get all chat sessions for a notebook."""
    try:
        notebook = await get_or_404(Notebook, notebook_id, "Notebook")

        sessions_list = await notebook.get_chat_sessions()

        results = []
        for session in sessions_list:
            session_id = str(session.id)

            msg_count = await get_session_message_count(chat_graph, session_id)

            results.append(
                ChatSessionResponse(
                    **session_to_response(
                        session,
                        notebook_id=notebook_id,
                        message_count=msg_count,
                        default_title="Untitled Session",
                    ),
                    context_config=getattr(session, "context_config", None),
                )
            )

        return results
    except Exception as e:
        logger.error(f"Error fetching chat sessions: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching chat sessions: {str(e)}"
        )


@router.post("/chat/sessions", response_model=ChatSessionResponse)
async def create_session(request: CreateSessionRequest):
    """Create a new chat session."""
    try:
        notebook = await get_or_404(Notebook, request.notebook_id, "Notebook")

        session = ChatSession(
            title=request.title
            or f"Chat Session {asyncio.get_event_loop().time():.0f}",
            model_override=request.model_override,
            parent_session_id=request.parent_session_id,
            quote=request.quote,
            tags=request.tags or [],
            context_config=request.context_config,
        )
        await session.save()

        await session.relate_to_notebook(request.notebook_id)

        return ChatSessionResponse(
            **session_to_response(
                session,
                notebook_id=request.notebook_id,
                message_count=0,
                default_title="",
            ),
            context_config=session.context_config,
        )
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
        full_session_id = ensure_prefix(session_id, "chat_session")
        session = await get_or_404(ChatSession, full_session_id, "Session")

        # Use sync get_state() in a thread since SqliteSaver doesn't support async
        thread_state = await asyncio.to_thread(
            chat_graph.get_state,
            config=RunnableConfig(configurable={"thread_id": full_session_id}),
        )

        messages: list[ChatMessage] = []
        if thread_state and thread_state.values and "messages" in thread_state.values:
            for msg in thread_state.values["messages"]:
                messages.append(await _build_chat_message(msg, len(messages)))

        notebook_id = await session.get_notebook_id()

        if not notebook_id:
            logger.warning(
                f"No notebook relationship found for session {session_id} - may be an orphaned session"
            )

        return ChatSessionWithMessagesResponse(
            **session_to_response(
                session,
                notebook_id=notebook_id,
                message_count=len(messages),
                default_title="Untitled Session",
            ),
            context_config=getattr(session, "context_config", None),
            messages=messages,
        )
    except Exception as e:
        logger.error(f"Error fetching session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching session: {str(e)}")


@router.put("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(session_id: str, request: UpdateSessionRequest):
    """Update session title."""
    try:
        full_session_id = ensure_prefix(session_id, "chat_session")
        session = await get_or_404(ChatSession, full_session_id, "Session")

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

        if "context_config" in update_data:
            session.context_config = update_data["context_config"]

        await session.save()

        notebook_id = await session.get_notebook_id()

        msg_count = await get_session_message_count(chat_graph, full_session_id)

        return ChatSessionResponse(
            **session_to_response(
                session,
                notebook_id=notebook_id,
                message_count=msg_count,
                default_title="",
            ),
            context_config=getattr(session, "context_config", None),
        )
    except Exception as e:
        logger.error(f"Error updating session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating session: {str(e)}")


@router.delete("/chat/sessions/{session_id}", response_model=SuccessResponse)
async def delete_session(session_id: str):
    """Delete a chat session."""
    try:
        full_session_id = ensure_prefix(session_id, "chat_session")
        session = await get_or_404(ChatSession, full_session_id, "Session")

        await session.delete()

        return SuccessResponse(success=True, message="Session deleted successfully")
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting session: {str(e)}")
