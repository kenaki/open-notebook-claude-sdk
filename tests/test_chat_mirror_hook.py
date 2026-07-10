"""Unit tests for the study-memory mirror hook in ``commands/chat_commands.py``
(study-memory Track A, Chunk A3).

Every completed chat turn (notebook AND source) fire-and-forgets a
``mirror_chat_exchange`` job after ``graph.invoke`` succeeds (coordinator
decision 6: one mirror command, no graph edits). The single most important
property of this chunk: a mirror failure must NEVER fail the chat turn — that
guarantee lives in ``chat_completion_command``'s try/except around the
``_maybe_mirror_chat_exchange`` call, exercised end-to-end below.

Uses a minimal ``_FakeMessage`` stand-in (mirrors ``test_chat_message_build.py``)
so the pure-extraction tests need no LangChain/DB dependency.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from commands.chat_commands import (
    ChatCompletionInput,
    _last_ai_message_text_and_id,
    _maybe_mirror_chat_exchange,
    chat_completion_command,
)


class _FakeMessage:
    """Minimal LangChain-message stand-in: only the attributes the mirror
    hook actually reads (type, content, id)."""

    def __init__(self, mtype, content, msg_id=None):
        self.type = mtype
        self.content = content
        self.id = msg_id


def _graph_result(ai_content="The answer is 42.", ai_id="ai-abc123"):
    return {
        "messages": [
            _FakeMessage("human", "What is the answer?"),
            _FakeMessage("ai", ai_content, msg_id=ai_id),
        ]
    }


# --- _last_ai_message_text_and_id (pure) ------------------------------------


def test_last_ai_message_finds_newest_ai_message():
    content, mid = _last_ai_message_text_and_id(_graph_result())
    assert content == "The answer is 42."
    assert mid == "ai-abc123"


def test_last_ai_message_no_ai_message_returns_none():
    result = {"messages": [_FakeMessage("human", "hi")]}
    assert _last_ai_message_text_and_id(result) == (None, None)


def test_last_ai_message_non_dict_graph_result_returns_none():
    assert _last_ai_message_text_and_id(None) == (None, None)


def test_last_ai_message_accepts_non_ai_prefixed_id():
    """The source-chat graph does not stamp a stable ``ai-`` id (no graph
    edits per coordinator decision 6) — unlike the illustration trigger's
    ``_new_ai_message_id``, the mirror hook must still pick this up."""
    content, mid = _last_ai_message_text_and_id(
        _graph_result(ai_id="run-xyz-provider-id")
    )
    assert content == "The answer is 42."
    assert mid == "run-xyz-provider-id"


# --- _maybe_mirror_chat_exchange (direct) ------------------------------------


@pytest.mark.asyncio
async def test_mirror_notebook_scope_submits_with_notebook_id():
    input_data = ChatCompletionInput(
        session_id="chat_session:x",
        message="What is the answer?",
        kind="notebook",
        notebook_id="notebook:nb1",
    )
    with patch("commands.chat_commands.submit_command") as mock_submit:
        mock_submit.return_value = "cmd-1"
        await _maybe_mirror_chat_exchange(
            input_data, _graph_result(), "chat_session:x"
        )

    mock_submit.assert_called_once()
    args, _ = mock_submit.call_args
    assert args[0] == "open_notebook"
    assert args[1] == "mirror_chat_exchange"
    payload = args[2]
    assert payload["scope"] == "notebook"
    assert payload["notebook_id"] == "notebook:nb1"
    assert payload["source_id"] is None
    assert payload["annotation_ids"] == []
    assert payload["session_id"] == "chat_session:x"
    assert payload["message_id"] == "ai-abc123"
    assert payload["question"] == "What is the answer?"
    assert payload["answer"] == "The answer is 42."


@pytest.mark.asyncio
async def test_mirror_source_scope_submits_with_source_id_and_annotation_ids():
    refs = [{"id": "source_annotation:a1"}, {"id": "source_annotation:a2"}]
    input_data = ChatCompletionInput(
        session_id="chat_session:x",
        message="Explain this highlight",
        kind="source",
        source_id="source:s1",
        annotation_refs=refs,
    )
    with patch("commands.chat_commands.submit_command") as mock_submit:
        mock_submit.return_value = "cmd-2"
        await _maybe_mirror_chat_exchange(
            input_data, _graph_result(), "chat_session:x"
        )

    payload = mock_submit.call_args[0][2]
    assert payload["scope"] == "source"
    assert payload["source_id"] == "source:s1"
    assert payload["notebook_id"] is None
    assert payload["annotation_ids"] == [
        "source_annotation:a1",
        "source_annotation:a2",
    ]


@pytest.mark.asyncio
async def test_mirror_skips_when_ai_content_empty():
    input_data = ChatCompletionInput(
        session_id="chat_session:x",
        message="hi",
        kind="notebook",
        notebook_id="notebook:nb1",
    )
    empty_result = {"messages": [_FakeMessage("ai", "")]}
    with patch("commands.chat_commands.submit_command") as mock_submit:
        await _maybe_mirror_chat_exchange(input_data, empty_result, "chat_session:x")
    mock_submit.assert_not_called()


@pytest.mark.asyncio
async def test_mirror_skips_when_no_ai_message_present():
    input_data = ChatCompletionInput(
        session_id="chat_session:x",
        message="hi",
        kind="notebook",
        notebook_id="notebook:nb1",
    )
    no_ai_result = {"messages": [_FakeMessage("human", "hi")]}
    with patch("commands.chat_commands.submit_command") as mock_submit:
        await _maybe_mirror_chat_exchange(input_data, no_ai_result, "chat_session:x")
    mock_submit.assert_not_called()


# --- caller-level safety net: a mirror failure never fails the chat turn ----


@pytest.mark.asyncio
async def test_chat_completion_survives_mirror_submit_command_raising():
    """A raising ``submit_command`` must never fail the chat turn — this is
    the single most important property of this chunk. Exercises the full
    ``chat_completion_command`` (source branch) with the graph/session/DB
    seams mocked out."""
    input_data = ChatCompletionInput(
        session_id="chat_session:x",
        message="Explain this highlight",
        kind="source",
        source_id="source:s1",
    )

    fake_session = MagicMock()
    fake_session.model_override = None
    fake_session.quote = None
    fake_session.save = AsyncMock()

    fake_source_graph = MagicMock()
    fake_source_graph.get_state.return_value = MagicMock(values={})

    with patch(
        "commands.chat_commands.ChatSession.get", AsyncMock(return_value=fake_session)
    ), patch(
        "commands.chat_commands.source_chat_graph", fake_source_graph
    ), patch(
        "commands.chat_commands._run_graph", AsyncMock(return_value=_graph_result())
    ), patch(
        "commands.chat_commands.submit_command", side_effect=RuntimeError("boom")
    ) as mock_submit:
        output = await chat_completion_command(input_data)

    assert output.success is True
    mock_submit.assert_called_once()


@pytest.mark.asyncio
async def test_chat_completion_notebook_branch_survives_mirror_raising():
    """Same guarantee, notebook branch (the other of the two required
    branches — coordinator decision 6 says both)."""
    input_data = ChatCompletionInput(
        session_id="chat_session:x",
        message="What is the answer?",
        kind="notebook",
        notebook_id="notebook:nb1",
    )

    fake_session = MagicMock()
    fake_session.model_override = None
    fake_session.quote = None
    fake_session.save = AsyncMock()

    fake_notebook_graph = MagicMock()
    fake_notebook_graph.get_state.return_value = MagicMock(values={})

    with patch(
        "commands.chat_commands.ChatSession.get", AsyncMock(return_value=fake_session)
    ), patch(
        "commands.chat_commands.Notebook.get", AsyncMock(return_value=None)
    ), patch(
        "commands.chat_commands.chat_graph", fake_notebook_graph
    ), patch(
        "commands.chat_commands._run_graph", AsyncMock(return_value=_graph_result())
    ), patch(
        # Isolate the mirror hook from the (separately-owned) auto-illustrate
        # trigger, which would otherwise also call submit_command for this
        # notebook branch and double-count the assertion below.
        "commands.chat_commands._maybe_trigger_illustration", AsyncMock()
    ), patch(
        "commands.chat_commands.submit_command", side_effect=RuntimeError("boom")
    ) as mock_submit:
        output = await chat_completion_command(input_data)

    assert output.success is True
    mock_submit.assert_called_once()
