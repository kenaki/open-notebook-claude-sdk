"""Unit tests for Claude Agent model selection.

These cover the pure resolution logic (no DB / no SDK subprocess):
- ``_build_options`` model precedence: explicit arg > CLAUDE_AGENT_MODEL env > default
- the Settings response mapping: the FOLLOW_DEFAULT sentinel / empty name => None
"""

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from langchain_core.messages import HumanMessage, SystemMessage

import open_notebook.ai.claude_agent as ca
from api.routers.models import _claude_agent_response
from open_notebook.ai.context_windows import get_context_window


class _Record:
    """Minimal stand-in for a Model record (only ``name`` is read)."""

    def __init__(self, name):
        self.name = name


def test_build_options_pins_explicit_model(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    monkeypatch.setattr(ca, "CLAUDE_AGENT_MODEL", None)

    options = ca._build_options("sys", model="claude-opus-4-8")

    assert options.model == "claude-opus-4-8"


def test_build_options_explicit_model_wins_over_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    monkeypatch.setattr(ca, "CLAUDE_AGENT_MODEL", "sonnet")

    options = ca._build_options("sys", model="claude-opus-4-8")

    assert options.model == "claude-opus-4-8"


def test_build_options_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    monkeypatch.setattr(ca, "CLAUDE_AGENT_MODEL", "sonnet")

    options = ca._build_options("sys", model=None)

    assert options.model == "sonnet"


def test_build_options_no_model_follows_default(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    monkeypatch.setattr(ca, "CLAUDE_AGENT_MODEL", None)

    options = ca._build_options("sys", model=None)

    assert getattr(options, "model", None) is None


def test_response_sentinel_name_maps_to_none(monkeypatch):
    monkeypatch.setattr(ca, "CLAUDE_AGENT_MODEL", None)
    resp = _claude_agent_response(_Record(ca.CLAUDE_AGENT_FOLLOW_DEFAULT))
    assert resp.model is None
    assert resp.env_override is None
    assert any(opt.value == "" for opt in resp.options)


def test_response_empty_name_maps_to_none():
    resp = _claude_agent_response(_Record(""))
    assert resp.model is None


def test_response_real_name_is_pinned():
    resp = _claude_agent_response(_Record("claude-opus-4-8"))
    assert resp.model == "claude-opus-4-8"


@pytest.mark.asyncio
async def test_is_selected_recognizes_composite_override():
    assert await ca.is_claude_agent_selected("claude_agent::claude-opus-4-8") is True


@pytest.mark.asyncio
async def test_get_model_parses_composite_override():
    model = await ca.get_claude_agent_model("claude_agent::claude-sonnet-4-6")
    assert model == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_get_model_composite_strips_whitespace():
    model = await ca.get_claude_agent_model("claude_agent::  opus  ")
    assert model == "opus"


# --- Chunk 4: tool-use disclosure capture -----------------------------------


def test_stringify_tool_result_passthrough_and_none():
    assert ca._stringify_tool_result(None) is None
    assert ca._stringify_tool_result("plain") == "plain"


def test_stringify_tool_result_text_blocks():
    content = [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]
    assert ca._stringify_tool_result(content) == "first\nsecond"


def test_stringify_tool_result_non_text_falls_back_to_json():
    out = ca._stringify_tool_result([{"type": "image", "data": "abc"}])
    assert "image" in out and "abc" in out


def _result_message(text, usage=None):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="s",
        result=text,
        usage=usage,
    )


def _fake_query(messages):
    """Build a stand-in for ``ca.query`` yielding the given SDK messages."""

    async def _gen(prompt, options):  # signature mirrors query(prompt=, options=)
        for m in messages:
            yield m

    return _gen


@pytest.mark.asyncio
async def test_run_captures_tool_uses_and_matches_results(monkeypatch):
    messages = [
        AssistantMessage(
            content=[
                ToolUseBlock(
                    id="tu_1",
                    name="mcp__open_notebook__search",
                    input={"query": "greek", "limit": 5},
                ),
            ],
            model="claude",
        ),
        UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="tu_1",
                    content=[{"type": "text", "text": "{\"count\": 2}"}],
                    is_error=False,
                ),
            ],
        ),
        AssistantMessage(content=[TextBlock(text="Found 2 results.")], model="claude"),
        _result_message("Found 2 results."),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    text, tool_uses, usage, model, thinking_texts = await ca._run("prompt", options=None)

    assert text == "Found 2 results."
    assert usage == {}  # no usage on the ResultMessage
    assert model == "claude"
    assert thinking_texts == []
    assert len(tool_uses) == 1
    disclosure = tool_uses[0]
    assert disclosure == {
        "id": "tu_1",
        "tool_name": "mcp__open_notebook__search",
        "tool_input": {"query": "greek", "limit": 5},
        "tool_result": '{"count": 2}',
        "is_error": False,
    }


@pytest.mark.asyncio
async def test_run_no_tools_returns_empty_list(monkeypatch):
    messages = [
        AssistantMessage(content=[TextBlock(text="Hi there.")], model="claude"),
        _result_message("Hi there."),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    text, tool_uses, _usage, _model, _thinking = await ca._run("prompt", options=None)

    assert text == "Hi there."
    assert tool_uses == []


# --- N2 USAGE-BE: per-turn token usage capture --------------------------------


@pytest.mark.asyncio
async def test_run_captures_usage_and_last_model_wins(monkeypatch):
    usage = {"input_tokens": 12, "output_tokens": 34}
    messages = [
        AssistantMessage(content=[TextBlock(text="Thinking...")], model="claude"),
        AssistantMessage(
            content=[TextBlock(text="Done.")], model="claude-opus-4-8"
        ),
        _result_message("Done.", usage=usage),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    text, _tool_uses, got_usage, model, _thinking = await ca._run("prompt", options=None)

    assert text == "Done."
    assert got_usage == usage
    # The LAST AssistantMessage's model id wins.
    assert model == "claude-opus-4-8"


# --- Chunk A4: tool_call/tool_result live events + ThinkingBlock capture -----


@pytest.mark.asyncio
async def test_run_emits_tool_call_and_result_events_when_job_id_given(monkeypatch):
    messages = [
        AssistantMessage(
            content=[
                ToolUseBlock(
                    id="tu_1",
                    name="mcp__open_notebook__search",
                    input={"query": "x"},
                ),
            ],
            model="claude",
        ),
        UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="tu_1",
                    content=[{"type": "text", "text": "ok"}],
                    is_error=False,
                ),
            ],
        ),
        AssistantMessage(content=[TextBlock(text="Done.")], model="claude"),
        _result_message("Done."),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    events = []

    async def fake_append_job_event(job_id, event_type, **payload):
        events.append((job_id, event_type, payload))

    monkeypatch.setattr(ca, "append_job_event", fake_append_job_event)

    text, _tool_uses, _usage, _model, _thinking = await ca._run(
        "prompt", options=None, job_id="command:test1"
    )

    assert text == "Done."
    assert [e[1] for e in events] == ["tool_call", "tool_result"]
    assert all(e[0] == "command:test1" for e in events)
    call_payload = events[0][2]
    assert call_payload == {
        "tool_name": "mcp__open_notebook__search",
        "tool_input": {"query": "x"},
    }
    result_payload = events[1][2]
    assert result_payload == {
        "tool_name": "mcp__open_notebook__search",
        "preview": "ok",
        "is_error": False,
    }


@pytest.mark.asyncio
async def test_run_without_job_id_emits_no_events(monkeypatch):
    messages = [
        AssistantMessage(
            content=[
                ToolUseBlock(id="tu_1", name="search", input={}),
            ],
            model="claude",
        ),
        UserMessage(
            content=[
                ToolResultBlock(tool_use_id="tu_1", content="ok", is_error=False),
            ],
        ),
        _result_message("Done."),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    events = []

    async def fake_append_job_event(job_id, event_type, **payload):
        events.append((job_id, event_type, payload))

    monkeypatch.setattr(ca, "append_job_event", fake_append_job_event)

    await ca._run("prompt", options=None)  # job_id defaults to None

    # append_job_event is still called (best-effort no-op inside), but with
    # job_id=None so the real helper would swallow it before touching the DB.
    assert all(e[0] is None for e in events)


@pytest.mark.asyncio
async def test_run_captures_thinking_block_text(monkeypatch):
    messages = [
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="Let me consider the sources.", signature="s1"),
                TextBlock(text="Here is the answer."),
            ],
            model="claude",
        ),
        _result_message("Here is the answer."),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    text, _tool_uses, _usage, _model, thinking_texts = await ca._run(
        "prompt", options=None
    )

    assert text == "Here is the answer."
    assert thinking_texts == ["Let me consider the sources."]


@pytest.mark.asyncio
async def test_run_ignores_empty_thinking_block(monkeypatch):
    messages = [
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="", signature="s1"),
                TextBlock(text="Answer."),
            ],
            model="claude",
        ),
        _result_message("Answer."),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    _text, _tool_uses, _usage, _model, thinking_texts = await ca._run(
        "prompt", options=None
    )

    assert thinking_texts == []


def test_build_usage_kwargs_copies_only_known_int_fields():
    sdk_usage = {
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 40,
        "service_tier": "standard",  # non-int extras must be dropped
        "server_tool_use": {"web_search_requests": 0},  # nested → dropped
        "cache_creation": {"ephemeral_5m_input_tokens": 40},  # nested → dropped
    }
    out = ca._build_usage_kwargs(sdk_usage, "claude-opus-4-8")
    assert out == {
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 40,
        "model": "claude-opus-4-8",
    }


def test_build_usage_kwargs_empty_or_none_returns_none():
    assert ca._build_usage_kwargs(None, "claude-opus-4-8") is None
    assert ca._build_usage_kwargs({}, "claude-opus-4-8") is None
    # Bools are ints in Python; they must not leak into token counts, and a
    # usage dict with no salvageable fields must not become an empty dict.
    assert ca._build_usage_kwargs({"input_tokens": True}, None) is None


def test_response_includes_env_override(monkeypatch):
    monkeypatch.setattr(ca, "CLAUDE_AGENT_MODEL", "sonnet")
    # The router reads its own module-level import of CLAUDE_AGENT_MODEL.
    import api.routers.models as routers_models

    monkeypatch.setattr(routers_models, "CLAUDE_AGENT_MODEL", "sonnet")
    resp = _claude_agent_response(_Record(ca.CLAUDE_AGENT_FOLLOW_DEFAULT))
    assert resp.env_override == "sonnet"


# --- Oversize system prompt: rerouted through stdin (E2BIG guard) ------------


def _stub_tools_module(monkeypatch):
    """Stand in for the lazy claude_agent_tools import (avoids the DB layer)."""
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "open_notebook.ai.claude_agent_tools",
        SimpleNamespace(
            MCP_SERVER_NAME="open_notebook",
            build_open_notebook_mcp_server=lambda: {"type": "sdk"},
        ),
    )


def _capture_run(monkeypatch):
    captured = {}

    async def fake_run(prompt, options, job_id=None):
        captured["prompt"] = prompt
        captured["options"] = options
        captured["job_id"] = job_id
        return "ok", [], {}, None, []

    monkeypatch.setattr(ca, "_run", fake_run)
    return captured


@pytest.mark.asyncio
async def test_generate_small_system_prompt_stays_as_append(tmp_path, monkeypatch):
    from langchain_core.messages import HumanMessage, SystemMessage

    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    _stub_tools_module(monkeypatch)
    captured = _capture_run(monkeypatch)

    await ca.generate_with_claude_agent(
        [SystemMessage(content="be brief"), HumanMessage(content="hi")]
    )

    assert captured["options"].system_prompt["append"] == "be brief"
    assert captured["prompt"] == "User: hi\n\n"


@pytest.mark.asyncio
async def test_generate_oversize_system_prompt_moves_to_transcript(
    tmp_path, monkeypatch
):
    from langchain_core.messages import HumanMessage, SystemMessage

    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    _stub_tools_module(monkeypatch)
    captured = _capture_run(monkeypatch)

    big = "x" * (ca.MAX_SYSTEM_PROMPT_ARG_BYTES + 1)
    await ca.generate_with_claude_agent(
        [SystemMessage(content=big), HumanMessage(content="hi")]
    )

    # The huge context rides on stdin (the transcript), not the CLI arg.
    assert captured["prompt"].startswith("<notebook_instructions>\n")
    assert big in captured["prompt"]
    assert captured["prompt"].endswith("User: hi\n\n")
    append = captured["options"].system_prompt["append"]
    assert append == ca.OVERSIZE_SYSTEM_PROMPT_STUB
    assert len(append.encode("utf-8")) < ca.MAX_SYSTEM_PROMPT_ARG_BYTES


# --- N2 USAGE-BE: usage rides AIMessage.additional_kwargs ---------------------


@pytest.mark.asyncio
async def test_generate_attaches_usage_with_model(tmp_path, monkeypatch):
    from langchain_core.messages import HumanMessage, SystemMessage

    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    _stub_tools_module(monkeypatch)
    sdk_usage = {
        "input_tokens": 12,
        "output_tokens": 34,
        "cache_read_input_tokens": 56,
        "cache_creation_input_tokens": 78,
        "service_tier": "standard",  # dropped: not a contract field
    }
    messages = [
        AssistantMessage(content=[TextBlock(text="Hi.")], model="claude-opus-4-8"),
        _result_message("Hi.", usage=sdk_usage),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    message = await ca.generate_with_claude_agent(
        [SystemMessage(content="sys"), HumanMessage(content="hi")]
    )

    assert message.content == "Hi."
    assert message.additional_kwargs["usage"] == {
        "input_tokens": 12,
        "output_tokens": 34,
        "cache_read_input_tokens": 56,
        "cache_creation_input_tokens": 78,
        "model": "claude-opus-4-8",
    }
    # tool_uses plumbing is untouched.
    assert message.additional_kwargs["tool_uses"] == []


@pytest.mark.asyncio
async def test_generate_passes_job_id_through_to_run(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    _stub_tools_module(monkeypatch)
    captured = _capture_run(monkeypatch)

    await ca.generate_with_claude_agent(
        [SystemMessage(content="sys"), HumanMessage(content="hi")],
        job_id="command:abc123",
    )

    assert captured["job_id"] == "command:abc123"


@pytest.mark.asyncio
async def test_generate_sets_thinking_kwarg_from_thinking_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    _stub_tools_module(monkeypatch)
    messages = [
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="Step one.", signature="s"),
                ThinkingBlock(thinking="Step two.", signature="s"),
                TextBlock(text="Final answer."),
            ],
            model="claude-opus-4-8",
        ),
        _result_message("Final answer."),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    message = await ca.generate_with_claude_agent(
        [SystemMessage(content="sys"), HumanMessage(content="hi")]
    )

    assert message.content == "Final answer."
    assert message.additional_kwargs["thinking"] == "Step one.\n\nStep two."


@pytest.mark.asyncio
async def test_generate_omits_thinking_key_when_no_thinking_blocks(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    _stub_tools_module(monkeypatch)
    messages = [
        AssistantMessage(content=[TextBlock(text="Hi.")], model="claude"),
        _result_message("Hi."),
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    message = await ca.generate_with_claude_agent(
        [SystemMessage(content="sys"), HumanMessage(content="hi")]
    )

    assert "thinking" not in message.additional_kwargs


@pytest.mark.asyncio
async def test_generate_without_usage_omits_key(tmp_path, monkeypatch):
    from langchain_core.messages import HumanMessage, SystemMessage

    monkeypatch.setattr(ca, "CLAUDE_AGENT_CWD", str(tmp_path))
    _stub_tools_module(monkeypatch)
    messages = [
        AssistantMessage(content=[TextBlock(text="Hi.")], model="claude"),
        _result_message("Hi."),  # no usage on the ResultMessage
    ]
    monkeypatch.setattr(ca, "query", _fake_query(messages))

    message = await ca.generate_with_claude_agent(
        [SystemMessage(content="sys"), HumanMessage(content="hi")]
    )

    # No empty dict in the checkpoint: the key is absent entirely.
    assert "usage" not in message.additional_kwargs
    assert message.additional_kwargs["tool_uses"] == []


# --- N2 USAGE-BE: context-window map ------------------------------------------


def test_context_window_claude_prefix():
    assert get_context_window("claude-opus-4-8") == 200_000
    assert get_context_window("claude-sonnet-4-6") == 200_000
    assert get_context_window("claude-haiku-4-5-20251001") == 200_000


def test_context_window_claude_aliases():
    assert get_context_window("opus") == 200_000
    assert get_context_window("sonnet") == 200_000
    assert get_context_window("haiku") == 200_000
    assert get_context_window("Sonnet") == 200_000  # case-insensitive


def test_context_window_qwen():
    assert get_context_window("qwen3.6") == 262_144
    assert get_context_window("qwen3.6:latest") == 262_144


def test_context_window_unknown_and_none():
    assert get_context_window("gpt-4o") is None
    assert get_context_window("") is None
    assert get_context_window("   ") is None
    assert get_context_window(None) is None
