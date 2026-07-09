from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


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
    context_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Per-chat source/note context selection; null = inherit notebook default",
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
    context_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Per-chat source/note context selection; null = inherit notebook default",
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


class UsageInfo(BaseModel):
    """Per-turn token usage for an AI message (frozen contract #9).

    Populated on the Claude Agent path; Esperanto messages carry no usage and
    serialize as ``usage: null``. All fields optional — the frontend meter
    renders whatever subset exists and hides when ``context_window`` is null.
    """

    input_tokens: Optional[int] = Field(
        None, description="Prompt tokens sent for this turn"
    )
    output_tokens: Optional[int] = Field(
        None, description="Completion tokens generated for this turn"
    )
    cache_read_input_tokens: Optional[int] = Field(
        None, description="Prompt tokens served from the prompt cache"
    )
    cache_creation_input_tokens: Optional[int] = Field(
        None, description="Prompt tokens written to the prompt cache"
    )
    model: Optional[str] = Field(
        None, description="Effective model id that produced this turn"
    )
    context_window: Optional[int] = Field(
        None,
        description="Model context-window size in tokens (meter denominator); null = unknown",
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
    usage: Optional[UsageInfo] = Field(
        None, description="Per-turn token usage (Claude Agent path only)"
    )
    thinking: Optional[str] = Field(
        None, description="Extracted <think> reasoning, if the model produced any"
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
    context_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Per-chat source/note context selection; null = inherit notebook default",
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


class ExecuteChatJobResponse(BaseModel):
    job_id: str = Field(..., description="Background job ID")
    session_id: str = Field(..., description="Chat session ID")


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
