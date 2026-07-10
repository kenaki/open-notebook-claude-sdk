"""
Unit tests for `_build_chat_message` (api/routers/chat/citations.py), covering
the A2 thinking-persistence contract: `ChatMessage.thinking` is populated when
`additional_kwargs.thinking` is present, and degrades safely to `None` when
absent (old messages checkpointed before this change).
"""

import pytest

from api.routers.chat.citations import _build_chat_message


class _FakeMessage:
    """Minimal stand-in for a LangChain message: only the attributes
    `_build_chat_message` actually reads (type, content, id, additional_kwargs).
    Using a plain object (not AIMessage) keeps this a pure unit test with no
    LangChain/DB dependency: content has no citation markers, so
    `_resolve_citations` never issues a query, and the id deliberately does not
    start with `ai-` so the ChatMessageMedia sidecar hydration is skipped."""

    def __init__(self, additional_kwargs=None, mtype="human", content="hello", msg_id="msg_0"):
        self.type = mtype
        self.content = content
        self.id = msg_id
        self.additional_kwargs = additional_kwargs or {}


@pytest.mark.asyncio
async def test_build_chat_message_with_thinking_populates_field():
    msg = _FakeMessage(additional_kwargs={"thinking": "step 1: consider the question"})
    result = await _build_chat_message(msg, 0)
    assert result.thinking == "step 1: consider the question"


@pytest.mark.asyncio
async def test_build_chat_message_without_thinking_defaults_to_none():
    """Old messages checkpointed before A2 lack the `thinking` key entirely —
    must degrade safely to None rather than raising."""
    msg = _FakeMessage(additional_kwargs={})
    result = await _build_chat_message(msg, 0)
    assert result.thinking is None


@pytest.mark.asyncio
async def test_build_chat_message_thinking_coexists_with_tool_uses():
    """thinking and tool_uses both ride on additional_kwargs (mirrored pattern);
    confirm one doesn't clobber the other."""
    msg = _FakeMessage(
        additional_kwargs={
            "thinking": "reasoning trace",
            "tool_uses": [
                {
                    "id": "call_1",
                    "tool_name": "search_sources",
                    "tool_input": {"query": "x"},
                    "tool_result": "found it",
                    "is_error": False,
                }
            ],
        }
    )
    result = await _build_chat_message(msg, 0)
    assert result.thinking == "reasoning trace"
    assert result.tool_uses is not None
    assert result.tool_uses[0].tool_name == "search_sources"


@pytest.mark.asyncio
async def test_build_chat_message_empty_thinking_string_is_none():
    """An empty-string thinking value (shouldn't normally happen, but the
    parser can return '') must not surface as a truthy-but-empty field."""
    msg = _FakeMessage(additional_kwargs={"thinking": ""})
    result = await _build_chat_message(msg, 0)
    assert result.thinking is None


# --- recall_refs (study-memory Track B, chunk B3) --------------------------


_RAW_EXCHANGE_REF = {
    "id": "chat_exchange:abc123",  # backend-only key — must be dropped
    "kind": "exchange",
    "title": "Kinematics discussion",
    "session_id": "chat_session:xyz",
    "scope": "notebook",
    "source_id": None,
    "notebook_id": "notebook:1",
    "message_id": "ai-42",
    "annotation_id": None,
    "page": None,
    "quote": "what is acceleration?",
    "similarity": 0.82,
}


@pytest.mark.asyncio
async def test_build_chat_message_with_recall_refs_serializes_contract_shape():
    msg = _FakeMessage(
        mtype="ai", additional_kwargs={"recall_refs": [_RAW_EXCHANGE_REF]}
    )
    result = await _build_chat_message(msg, 0)
    assert result.recall_refs is not None
    assert len(result.recall_refs) == 1
    ref = result.recall_refs[0]
    assert ref.kind == "exchange"
    assert ref.title == "Kinematics discussion"
    assert ref.session_id == "chat_session:xyz"
    assert ref.scope == "notebook"
    assert ref.notebook_id == "notebook:1"
    assert ref.message_id == "ai-42"
    assert ref.quote == "what is acceleration?"
    assert ref.similarity == 0.82


@pytest.mark.asyncio
async def test_build_chat_message_recall_refs_drops_backend_only_id_key():
    """recall_search emits an extra backend-only `id` key (X-recall-id-key);
    the frontend contract is exactly 11 fields and must never see it."""
    msg = _FakeMessage(
        mtype="ai", additional_kwargs={"recall_refs": [_RAW_EXCHANGE_REF]}
    )
    result = await _build_chat_message(msg, 0)
    ref = result.recall_refs[0]
    assert not hasattr(ref, "id")
    assert "id" not in ref.model_dump()


@pytest.mark.asyncio
async def test_build_chat_message_without_recall_refs_defaults_to_none():
    """Older sessions / messages with no recall_refs key must deserialize
    cleanly to None, never raise."""
    msg = _FakeMessage(mtype="ai", additional_kwargs={})
    result = await _build_chat_message(msg, 0)
    assert result.recall_refs is None


@pytest.mark.asyncio
async def test_build_chat_message_human_turn_carries_no_recall_refs():
    msg = _FakeMessage(mtype="human", additional_kwargs={}, content="hello")
    result = await _build_chat_message(msg, 0)
    assert result.recall_refs is None
