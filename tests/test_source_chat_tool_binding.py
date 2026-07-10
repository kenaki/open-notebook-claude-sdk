"""Unit tests for study-memory Chunk B2 — source-chat tool binding + the
Claude-agent tool_uses -> recall_refs capture.

No real model/DB/LLM: source chat's Esperanto branch is exercised with a fake
model + monkeypatched ``_stream_model``/``CHAT_TOOLS``, mirroring the
established pattern in ``tests/test_stream_model.py``. The Claude-agent scan
is exercised directly against ``open_notebook.ai.claude_agent._extract_recall_refs``
with synthetic ``tool_uses`` dicts (the exact shape ``_run`` returns).
"""

import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

import open_notebook.ai.claude_agent as ca
import open_notebook.graphs.chat as chat
import open_notebook.graphs.source_chat as source_chat


# --- source_chat.py: bind_tools fallback intact -------------------------------


class _FakeModelNoTools:
    """A model whose bind_tools() raises NotImplementedError, like a
    tool-calling-incapable Esperanto/local model."""

    def __init__(self):
        self.bind_tools_called = False

    def bind_tools(self, tools):
        self.bind_tools_called = True
        raise NotImplementedError("this model does not support tool calling")


@pytest.mark.asyncio
async def test_source_chat_falls_back_when_bind_tools_not_implemented(monkeypatch):
    """When the model can't bind tools, source chat must still answer
    normally via the original bare `_stream_model` call — no regression."""
    fake_model = _FakeModelNoTools()

    async def fake_is_claude_agent_selected(model_id):
        return False

    async def fake_provision(*args, **kwargs):
        return fake_model

    calls = []

    async def fake_stream_model(model, payload, job_id):
        calls.append(model)
        return AIMessage(content="plain answer")

    monkeypatch.setattr(
        source_chat, "is_claude_agent_selected", fake_is_claude_agent_selected
    )
    monkeypatch.setattr(source_chat, "provision_langchain_model", fake_provision)
    monkeypatch.setattr(source_chat, "_stream_model", fake_stream_model)

    result = await source_chat._generate_source_chat_message(
        model_id="model:local",
        payload=[HumanMessage(content="hello")],
        config={},
    )

    assert fake_model.bind_tools_called is True
    # Fallback path: _stream_model called exactly once, with the PLAIN model
    # (not a tools-bound wrapper), and its result returned untouched.
    assert len(calls) == 1
    assert calls[0] is fake_model
    assert result.content == "plain answer"


# --- source_chat.py: bound path runs the tool loop + captures recall_refs ----


class _FakeBoundModel:
    """Stands in for `model.bind_tools(CHAT_TOOLS)`'s return value."""


class _FakeModelWithTools:
    def __init__(self):
        self.bound = _FakeBoundModel()

    def bind_tools(self, tools):
        return self.bound


class _FakeRecallTool:
    name = "search_past_discussions"

    def __init__(self, result):
        self._result = result

    async def ainvoke(self, args):
        return self._result


@pytest.mark.asyncio
async def test_source_chat_bound_path_runs_tool_loop_and_captures_recall_refs(
    monkeypatch,
):
    """When the model DOES support tool calling, source chat binds CHAT_TOOLS
    and runs `_run_tool_loop` — recall refs from `search_past_discussions`
    ride into the final message the same way notebook chat does (B1)."""
    fake_model = _FakeModelWithTools()

    async def fake_is_claude_agent_selected(model_id):
        return False

    async def fake_provision(*args, **kwargs):
        return fake_model

    refs = [
        {
            "kind": "exchange",
            "title": "Prior source chat",
            "session_id": "chat_session:xyz",
            "scope": "source",
            "source_id": "source:s1",
            "notebook_id": None,
            "message_id": "ai-1",
            "annotation_id": None,
            "page": None,
            "quote": "What is entropy?",
            "similarity": 0.81,
        }
    ]
    fake_tool = _FakeRecallTool(json.dumps({"results": refs, "count": 1}))

    tool_call_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_past_discussions",
                "args": {"query": "entropy"},
                "id": "c1",
                "type": "tool_call",
            }
        ],
    )
    final_message = AIMessage(content="final answer", tool_calls=[])

    call_count = {"n": 0}

    async def fake_stream_model(model, payload, job_id):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return tool_call_message
        return final_message

    async def fake_report_progress(*args, **kwargs):
        return None

    async def fake_append_event(*args, **kwargs):
        return None

    monkeypatch.setattr(
        source_chat, "is_claude_agent_selected", fake_is_claude_agent_selected
    )
    monkeypatch.setattr(source_chat, "provision_langchain_model", fake_provision)
    # The first stream call happens via source_chat's own imported reference;
    # the second (inside _run_tool_loop) happens via chat.py's module global —
    # both must be patched to the same fake for the round-trip to work.
    monkeypatch.setattr(source_chat, "_stream_model", fake_stream_model)
    monkeypatch.setattr(chat, "_stream_model", fake_stream_model)
    monkeypatch.setattr(chat, "CHAT_TOOLS", [fake_tool])
    monkeypatch.setattr(chat, "report_job_progress", fake_report_progress)
    monkeypatch.setattr(chat, "append_job_event", fake_append_event)

    result = await source_chat._generate_source_chat_message(
        model_id="model:local",
        payload=[HumanMessage(content="what did we say about entropy?")],
        config={},
        job_id="command:src1",
    )

    assert call_count["n"] == 2
    assert result.content == "final answer"
    assert result.additional_kwargs["recall_refs"] == refs
    assert result.additional_kwargs["tool_uses"][0]["tool_name"] == (
        "search_past_discussions"
    )


# --- claude_agent.py: tool_uses -> recall_refs scan ---------------------------


def _disclosure(tool_name, result_dict=None, raw_result=None, is_error=False):
    return {
        "id": "id1",
        "tool_name": tool_name,
        "tool_input": {},
        "tool_result": raw_result if raw_result is not None else (
            json.dumps(result_dict) if result_dict is not None else None
        ),
        "is_error": is_error,
    }


def test_extract_recall_refs_empty_when_no_tool_uses():
    assert ca._extract_recall_refs([]) == []
    assert ca._extract_recall_refs(None) == []


def test_extract_recall_refs_matches_mcp_prefixed_tool_name():
    """MCP tool names are prefixed (mcp__open_notebook__<tool>); the scan
    must match on suffix, not exact name."""
    ref = {
        "kind": "annotation",
        "annotation_id": "source_annotation:a1",
        "similarity": 0.6,
    }
    tool_uses = [
        _disclosure(
            "mcp__open_notebook__search_past_discussions",
            result_dict={"results": [ref], "count": 1},
        )
    ]
    out = ca._extract_recall_refs(tool_uses)
    assert out == [ref]


def test_extract_recall_refs_ignores_unrelated_tools():
    tool_uses = [
        _disclosure(
            "mcp__open_notebook__search",
            result_dict={"results": [{"kind": "exchange"}]},
        )
    ]
    assert ca._extract_recall_refs(tool_uses) == []


def test_extract_recall_refs_dedupes_and_caps():
    high = {"kind": "exchange", "session_id": "chat_session:a", "similarity": 0.9}
    low = {"kind": "exchange", "session_id": "chat_session:a", "similarity": 0.4}
    other = {
        "kind": "annotation",
        "annotation_id": "source_annotation:b",
        "similarity": 0.7,
    }
    tool_uses = [
        _disclosure(
            "mcp__open_notebook__search_past_discussions",
            result_dict={"results": [low, other]},
        ),
        _disclosure(
            "mcp__open_notebook__search_past_discussions",
            result_dict={"results": [high]},
        ),
    ]
    out = ca._extract_recall_refs(tool_uses)
    # Deduped by session_id (keeps the higher-similarity row), sorted desc.
    assert out == [high, other]


def test_extract_recall_refs_skips_malformed_json_without_raising():
    tool_uses = [
        _disclosure(
            "mcp__open_notebook__search_past_discussions", raw_result="not json"
        ),
        _disclosure(
            "mcp__open_notebook__search_past_discussions",
            result_dict={
                "results": [
                    {
                        "kind": "exchange",
                        "session_id": "chat_session:ok",
                        "similarity": 0.5,
                    }
                ]
            },
        ),
    ]
    # Must not raise despite the malformed first entry.
    out = ca._extract_recall_refs(tool_uses)
    assert len(out) == 1
    assert out[0]["session_id"] == "chat_session:ok"


def test_extract_recall_refs_skips_error_disclosures():
    tool_uses = [
        _disclosure(
            "mcp__open_notebook__search_past_discussions",
            result_dict={"results": [{"kind": "exchange", "similarity": 1.0}]},
            is_error=True,
        )
    ]
    assert ca._extract_recall_refs(tool_uses) == []


def test_extract_recall_refs_skips_missing_or_non_list_results():
    tool_uses = [
        _disclosure("mcp__open_notebook__search_past_discussions", raw_result=None),
        _disclosure(
            "mcp__open_notebook__search_past_discussions",
            result_dict={"results": "not-a-list"},
        ),
        _disclosure(
            "mcp__open_notebook__search_past_discussions", result_dict={"count": 0}
        ),
    ]
    assert ca._extract_recall_refs(tool_uses) == []
