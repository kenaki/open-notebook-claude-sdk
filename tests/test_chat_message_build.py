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
