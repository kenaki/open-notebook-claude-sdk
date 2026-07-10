"""Unit tests for A3 — live thinking streaming (`_stream_model`) and the
tool-event half of `_run_tool_loop`.

No real model is used: a fake async-generator model feeds `.astream()`, and
`append_job_event` / `report_job_progress` are patched to recorders so we assert
the exact events emitted, their coalescing cadence, delta correctness (no
overlap / duplication across flushes), and the truncation marker.
"""

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

import open_notebook.graphs.chat as chat


class FakeStreamModel:
    """Stands in for a `bind_tools`-wrapped chat model.

    `.astream(messages)` yields the provided `AIMessageChunk`s in order.
    `.invoke(messages)` returns `invoke_result` (for the job_id=None fallback).
    Records whether each path was taken.
    """

    def __init__(self, chunks=None, invoke_result=None):
        self._chunks = chunks or []
        self._invoke_result = invoke_result
        self.astream_called = False
        self.invoke_called = False

    async def astream(self, messages):
        self.astream_called = True
        for chunk in self._chunks:
            yield chunk

    def invoke(self, messages):
        self.invoke_called = True
        return self._invoke_result


def _text_chunk(text):
    return AIMessageChunk(content=text)


@pytest.fixture
def recorder(monkeypatch):
    """Patch chat.append_job_event and chat.report_job_progress to recorders."""
    events = []
    phases = []

    async def fake_append(job_id, event_type, **payload):
        events.append((event_type, payload))

    async def fake_report(job_id, phase, **extra):
        phases.append((phase, extra))

    monkeypatch.setattr(chat, "append_job_event", fake_append)
    monkeypatch.setattr(chat, "report_job_progress", fake_report)
    return {"events": events, "phases": phases}


# --- _stream_model: fallback ------------------------------------------------


@pytest.mark.asyncio
async def test_stream_model_job_id_none_falls_back_to_invoke(recorder):
    sentinel = AIMessage(content="from invoke")
    model = FakeStreamModel(invoke_result=sentinel)

    result = await chat._stream_model(model, [HumanMessage(content="hi")], job_id=None)

    assert result is sentinel
    assert model.invoke_called and not model.astream_called
    assert recorder["events"] == []


@pytest.mark.asyncio
async def test_stream_model_empty_stream_falls_back(recorder):
    sentinel = AIMessage(content="fallback")
    model = FakeStreamModel(chunks=[], invoke_result=sentinel)

    result = await chat._stream_model(model, [HumanMessage(content="hi")], job_id="cmd:1")

    assert result is sentinel
    assert model.astream_called and model.invoke_called


# --- _stream_model: accumulation reproduces invoke incl. tool_calls ---------


@pytest.mark.asyncio
async def test_stream_model_accumulates_content_and_tool_calls(recorder):
    chunks = [
        AIMessageChunk(content="Hello "),
        AIMessageChunk(content="world"),
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": "search_sources", "args": '{"query": "x"}', "id": "c1", "index": 0}
            ],
        ),
    ]
    model = FakeStreamModel(chunks=chunks)

    result = await chat._stream_model(model, [HumanMessage(content="q")], job_id="cmd:1")

    assert result.content == "Hello world"
    assert [tc["name"] for tc in result.tool_calls] == ["search_sources"]
    assert result.tool_calls[0]["args"] == {"query": "x"}


# --- _stream_model: thinking delta correctness (no overlap) -----------------


@pytest.mark.asyncio
async def test_stream_model_thinking_deltas_no_overlap(monkeypatch, recorder):
    # Force a flush on every chunk so cadence is deterministic.
    monkeypatch.setattr(chat, "_THINKING_FLUSH_CHARS", 0)

    # Two think blocks arriving in separate chunks; interleaved answer text.
    chunks = [
        _text_chunk("<think>alpha</think>"),
        _text_chunk("answer part "),
        _text_chunk("<think>beta</think>"),
        _text_chunk("done"),
    ]
    model = FakeStreamModel(chunks=chunks)

    result = await chat._stream_model(model, [HumanMessage(content="q")], job_id="cmd:1")

    thinking_events = [p["text"] for (t, p) in recorder["events"] if t == "thinking"]
    # Each block surfaces exactly once; concatenation equals the full parsed
    # thinking — proving no delta overlaps or duplicates another.
    full_thinking, _ = chat.parse_thinking_content(
        chat.extract_text_content(result.content)
    )
    assert "".join(thinking_events) == full_thinking
    assert full_thinking == "alpha\n\nbeta"
    assert thinking_events == ["alpha", "\n\nbeta"]
    # No phase (truncation) events for a short stream.
    assert not [t for (t, _p) in recorder["events"] if t == "phase"]


# --- A6: Ollama `reasoning_content` deltas -----------------------------------


@pytest.mark.asyncio
async def test_stream_model_reasoning_content_deltas_flush_and_normalize(
    monkeypatch, recorder
):
    """Reasoning arriving on `additional_kwargs["reasoning_content"]` (Ollama's
    `reasoning` field, A6) streams into thinking events on the same cadence as
    inline `<think>` tags, and the shared `extract_thinking` helper normalizes
    the accumulated result into `additional_kwargs["thinking"]` afterward."""
    monkeypatch.setattr(chat, "_THINKING_FLUSH_CHARS", 0)  # flush every chunk

    chunks = [
        AIMessageChunk(content="", additional_kwargs={"reasoning_content": "alpha "}),
        AIMessageChunk(content="", additional_kwargs={"reasoning_content": "beta"}),
        AIMessageChunk(content="answer"),
    ]
    model = FakeStreamModel(chunks=chunks)

    result = await chat._stream_model(model, [HumanMessage(content="q")], job_id="cmd:1")

    thinking_events = [p["text"] for (t, p) in recorder["events"] if t == "thinking"]
    assert "".join(thinking_events) == "alpha beta"
    assert result.additional_kwargs["reasoning_content"] == "alpha beta"
    assert result.content == "answer"

    # Downstream capture-site normalization (chat.py / source_chat.py, A6).
    content = chat.extract_text_content(result.content)
    thinking, cleaned = chat.extract_thinking(result, content)
    assert thinking == "alpha beta"
    assert cleaned == "answer"  # content had no inline tags to strip


@pytest.mark.asyncio
async def test_stream_model_tag_fallback_still_works_without_reasoning_content(
    recorder,
):
    """A tag-emitting model (no `reasoning_content` key at all) still flows
    through the `parse_thinking_content` fallback, unaffected by A6."""
    chunks = [_text_chunk("<think>tagged reasoning</think>"), _text_chunk("done")]
    model = FakeStreamModel(chunks=chunks)

    result = await chat._stream_model(model, [HumanMessage(content="q")], job_id="cmd:1")

    thinking_events = [p["text"] for (t, p) in recorder["events"] if t == "thinking"]
    assert thinking_events == ["tagged reasoning"]
    assert "reasoning_content" not in result.additional_kwargs


def test_extract_thinking_never_overwrites_claude_agent_thinking():
    """A4's Claude-agent path already sets `additional_kwargs["thinking"]`
    directly; A6's normalization must never clobber it, even if `content`
    happens to also carry `reasoning_content` or inline tags."""
    message = AIMessage(
        content="clean claude-agent answer",
        additional_kwargs={
            "thinking": "claude thinking already set",
            "reasoning_content": "should be ignored",
        },
    )

    thinking, cleaned = chat.extract_thinking(message, message.content)

    assert thinking == "claude thinking already set"
    assert cleaned == message.content


def test_extract_thinking_prefers_reasoning_content_over_tags():
    """When both a `reasoning_content` field AND inline tags are present (should
    not happen in practice, but the precedence must be deterministic), the
    Ollama reasoning field wins."""
    message = AIMessage(
        content="<think>tagged</think>answer",
        additional_kwargs={"reasoning_content": "structured reasoning"},
    )

    thinking, cleaned = chat.extract_thinking(message, message.content)

    assert thinking == "structured reasoning"
    # Content is returned unchanged (not tag-stripped) when reasoning_content wins.
    assert cleaned == message.content


@pytest.mark.asyncio
async def test_stream_model_final_flush_captures_trailing_thinking(recorder):
    # Default thresholds (400 chars / 2s) are NOT hit by this tiny stream, so the
    # ONLY flush is the post-loop final flush — it must still emit the thinking.
    chunks = [_text_chunk("<think>late reasoning</think>"), _text_chunk("answer")]
    model = FakeStreamModel(chunks=chunks)

    await chat._stream_model(model, [HumanMessage(content="q")], job_id="cmd:1")

    thinking_events = [p["text"] for (t, p) in recorder["events"] if t == "thinking"]
    assert thinking_events == ["late reasoning"]


# --- _stream_model: truncation marker ---------------------------------------


@pytest.mark.asyncio
async def test_stream_model_truncates_after_cap(monkeypatch, recorder):
    monkeypatch.setattr(chat, "_THINKING_FLUSH_CHARS", 0)  # flush every chunk
    monkeypatch.setattr(chat, "_MAX_THINKING_EVENTS", 2)

    chunks = [
        _text_chunk("<think>one</think>"),
        _text_chunk("<think>two</think>"),
        _text_chunk("<think>three</think>"),
        _text_chunk("<think>four</think>"),
    ]
    model = FakeStreamModel(chunks=chunks)

    await chat._stream_model(model, [HumanMessage(content="q")], job_id="cmd:1")

    thinking_events = [p for (t, p) in recorder["events"] if t == "thinking"]
    phase_events = [p for (t, p) in recorder["events"] if t == "phase"]
    # Exactly the cap of thinking events, then exactly one truncation marker.
    assert len(thinking_events) == 2
    assert len(phase_events) == 1
    assert phase_events[0]["phase"] == "…thinking log truncated"


# --- _run_tool_loop: tool_call / tool_result events -------------------------


class _FakeTool:
    def __init__(self, name, result="found 3 sources", raise_exc=None):
        self.name = name
        self._result = result
        self._raise = raise_exc

    async def ainvoke(self, args):
        if self._raise is not None:
            raise self._raise
        return self._result


@pytest.mark.asyncio
async def test_run_tool_loop_emits_tool_events(monkeypatch, recorder):
    fake_tool = _FakeTool("search_sources", result="R" * 800)
    monkeypatch.setattr(chat, "CHAT_TOOLS", [fake_tool])

    # After the tool round-trip, the re-invoked model returns a final answer with
    # no further tool calls, ending the loop.
    final_model = FakeStreamModel(chunks=[AIMessageChunk(content="final answer")])

    first = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_sources", "args": {"query": "mito"}, "id": "c1", "type": "tool_call"}
        ],
    )

    result = await chat._run_tool_loop(
        final_model,
        [SystemMessage(content="sys"), HumanMessage(content="find mito")],
        first,
        job_id="cmd:9",
    )

    types = [t for (t, _p) in recorder["events"]]
    assert "tool_call" in types and "tool_result" in types
    # tool_call before tool_result.
    assert types.index("tool_call") < types.index("tool_result")

    call_ev = next(p for (t, p) in recorder["events"] if t == "tool_call")
    res_ev = next(p for (t, p) in recorder["events"] if t == "tool_result")
    assert call_ev["tool_name"] == "search_sources"
    assert call_ev["tool_input"] == {"query": "mito"}
    assert res_ev["tool_name"] == "search_sources"
    assert res_ev["is_error"] is False
    # Preview is capped at 500 chars.
    assert len(res_ev["preview"]) == 500

    # Phase progress still reported (back-compat live label).
    assert recorder["phases"] and recorder["phases"][0][0] == "Searching your sources"
    # Loop resolved to the final streamed answer, with tool disclosures attached.
    assert result.content == "final answer"
    assert result.additional_kwargs["tool_uses"][0]["tool_name"] == "search_sources"


@pytest.mark.asyncio
async def test_run_tool_loop_tool_error_marks_is_error(monkeypatch, recorder):
    fake_tool = _FakeTool("search_sources", raise_exc=RuntimeError("boom"))
    monkeypatch.setattr(chat, "CHAT_TOOLS", [fake_tool])
    final_model = FakeStreamModel(chunks=[AIMessageChunk(content="done")])

    first = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_sources", "args": {"query": "z"}, "id": "c1", "type": "tool_call"}
        ],
    )

    await chat._run_tool_loop(
        final_model, [HumanMessage(content="q")], first, job_id="cmd:9"
    )

    res_ev = next(p for (t, p) in recorder["events"] if t == "tool_result")
    assert res_ev["is_error"] is True
    assert "boom" in res_ev["preview"]


# --- _run_tool_loop: recall_refs capture (study-memory chunk B1) ------------


@pytest.mark.asyncio
async def test_run_tool_loop_captures_recall_refs(monkeypatch, recorder):
    """A clean search_past_discussions call feeds its metadata-only results
    into additional_kwargs["recall_refs"] (deduped/capped), alongside
    tool_uses — the same seam, only when non-empty."""
    import json

    refs = [
        {
            "kind": "exchange",
            "title": "Prior chat",
            "session_id": "chat_session:abc",
            "scope": "notebook",
            "source_id": None,
            "notebook_id": "notebook:nb1",
            "message_id": "ai-1",
            "annotation_id": None,
            "page": None,
            "quote": "What is a monad?",
            "similarity": 0.71,
        }
    ]
    fake_tool = _FakeTool(
        "search_past_discussions",
        result=json.dumps({"results": refs, "count": 1}),
    )
    monkeypatch.setattr(chat, "CHAT_TOOLS", [fake_tool])
    final_model = FakeStreamModel(chunks=[AIMessageChunk(content="final answer")])

    first = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_past_discussions",
                "args": {"query": "monad"},
                "id": "c1",
                "type": "tool_call",
            }
        ],
    )

    result = await chat._run_tool_loop(
        final_model,
        [HumanMessage(content="what did we say about monads?")],
        first,
        job_id="cmd:9",
    )

    assert result.additional_kwargs["recall_refs"] == refs
    assert result.additional_kwargs["tool_uses"][0]["tool_name"] == "search_past_discussions"


@pytest.mark.asyncio
async def test_run_tool_loop_no_recall_refs_key_when_no_results(monkeypatch, recorder):
    """search_sources (unrelated tool) never populates recall_refs; the key is
    absent entirely rather than an empty list."""
    fake_tool = _FakeTool("search_sources", result="found 3 sources")
    monkeypatch.setattr(chat, "CHAT_TOOLS", [fake_tool])
    final_model = FakeStreamModel(chunks=[AIMessageChunk(content="final answer")])

    first = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_sources", "args": {"query": "x"}, "id": "c1", "type": "tool_call"}
        ],
    )

    result = await chat._run_tool_loop(
        final_model, [HumanMessage(content="q")], first, job_id="cmd:9"
    )

    assert "recall_refs" not in result.additional_kwargs
