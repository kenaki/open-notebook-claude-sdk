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
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

import open_notebook.ai.claude_agent as ca
from api.routers.models import _claude_agent_response


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


def _result_message(text):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="s",
        result=text,
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

    text, tool_uses = await ca._run("prompt", options=None)

    assert text == "Found 2 results."
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

    text, tool_uses = await ca._run("prompt", options=None)

    assert text == "Hi there."
    assert tool_uses == []


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

    async def fake_run(prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        return "ok", []

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
