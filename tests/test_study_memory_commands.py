"""Unit tests for study-memory substrate commands (chunk A2).

Covers:
- ``embed_annotation_command``: text assembly (quote/note/tags), success,
  empty-text ValueError, not-found ValueError.
- ``_generate_gist`` / ``mirror_chat_exchange_command``: the output-sanity
  guard (coordinator decision 8, to-fix/004 lesson) — a normal gist passes
  through; an over-length or empty gist falls back to ``answer[:400]``; a
  model failure falls back too, and the exchange row is still created +
  embedded (a gist hiccup must never lose the exchange).

Everything here is mocked at the module-namespace level (no DB, no LLM).
"""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import commands.study_memory_commands as smc
from commands.study_memory_commands import (
    EmbedAnnotationInput,
    MirrorChatExchangeInput,
    _generate_gist,
    embed_annotation_command,
    mirror_chat_exchange_command,
)


def _response(content: str):
    resp = MagicMock()
    resp.content = content
    return resp


def _patch_gist_pipeline(monkeypatch, model=None, provision_side_effect=None):
    """Wire the model-provisioning chain that _generate_gist drives."""
    if provision_side_effect is not None:
        monkeypatch.setattr(
            smc,
            "provision_langchain_model",
            AsyncMock(side_effect=provision_side_effect),
        )
    else:
        monkeypatch.setattr(
            smc, "provision_langchain_model", AsyncMock(return_value=model)
        )
    monkeypatch.setattr(
        smc.model_manager,
        "get_defaults",
        AsyncMock(return_value=SimpleNamespace(default_transformation_model="model:t")),
    )
    monkeypatch.setattr(smc, "heavy_lane_for", AsyncMock(return_value=nullcontext()))
    monkeypatch.setattr(smc, "report_job_progress", AsyncMock())


# --- _generate_gist: the output-sanity guard --------------------------------


@pytest.mark.asyncio
async def test_gist_normal_reply_passes_through(monkeypatch):
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=_response("A concise 2-3 sentence gist."))
    _patch_gist_pipeline(monkeypatch, model=model)

    gist, used_fallback = await _generate_gist("the full answer text", "cmd-1")

    assert gist == "A concise 2-3 sentence gist."
    assert used_fallback is False


@pytest.mark.asyncio
async def test_gist_over_700_chars_falls_back_to_truncated_answer(monkeypatch):
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=_response("y" * 701))
    _patch_gist_pipeline(monkeypatch, model=model)
    answer = "z" * 1000

    gist, used_fallback = await _generate_gist(answer, "cmd-2")

    assert gist == answer[:400]
    assert used_fallback is True


@pytest.mark.asyncio
async def test_gist_at_exactly_700_chars_is_not_fallback(monkeypatch):
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=_response("y" * 700))
    _patch_gist_pipeline(monkeypatch, model=model)

    gist, used_fallback = await _generate_gist("answer", "cmd-2b")

    assert len(gist) == 700
    assert used_fallback is False


@pytest.mark.asyncio
async def test_gist_empty_reply_falls_back(monkeypatch):
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=_response(""))
    _patch_gist_pipeline(monkeypatch, model=model)
    answer = "the real answer content"

    gist, used_fallback = await _generate_gist(answer, "cmd-3")

    assert gist == answer[:400]
    assert used_fallback is True


@pytest.mark.asyncio
async def test_gist_whitespace_only_reply_falls_back(monkeypatch):
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=_response("   \n  "))
    _patch_gist_pipeline(monkeypatch, model=model)
    answer = "the real answer content"

    gist, used_fallback = await _generate_gist(answer, "cmd-3b")

    assert gist == answer[:400]
    assert used_fallback is True


@pytest.mark.asyncio
async def test_gist_model_provisioning_failure_falls_back(monkeypatch):
    """A gist failure (e.g. no model configured) must never raise — the
    caller relies on this to still create + embed the exchange row."""
    _patch_gist_pipeline(
        monkeypatch, provision_side_effect=RuntimeError("no model configured")
    )
    answer = "the real answer content that should survive"

    gist, used_fallback = await _generate_gist(answer, "cmd-4")

    assert gist == answer[:400]
    assert used_fallback is True


@pytest.mark.asyncio
async def test_gist_model_invoke_failure_falls_back(monkeypatch):
    model = MagicMock()
    model.ainvoke = AsyncMock(side_effect=RuntimeError("provider 502"))
    _patch_gist_pipeline(monkeypatch, model=model)
    answer = "another real answer"

    gist, used_fallback = await _generate_gist(answer, "cmd-5")

    assert gist == answer[:400]
    assert used_fallback is True


# --- mirror_chat_exchange_command: end to end (gist mocked out) -------------


def _saved_exchange_stub():
    """An AsyncMock-compatible .save() that stamps an id, like ObjectModel.save()."""

    async def _save(self):
        self.id = "chat_exchange:new1"

    return _save


@pytest.mark.asyncio
async def test_mirror_chat_exchange_success_with_normal_gist(monkeypatch):
    monkeypatch.setattr(
        smc, "_generate_gist", AsyncMock(return_value=("A tidy gist.", False))
    )
    monkeypatch.setattr(smc.ChatExchange, "save", _saved_exchange_stub())
    monkeypatch.setattr(smc, "report_job_progress", AsyncMock())
    mock_embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    monkeypatch.setattr(smc, "generate_embedding", mock_embed)
    mock_query = AsyncMock()
    monkeypatch.setattr(smc, "repo_query", mock_query)
    monkeypatch.setattr(smc, "ensure_record_id", lambda v: v)

    result = await mirror_chat_exchange_command(
        MirrorChatExchangeInput(
            session_id="chat_session:s1",
            scope="notebook",
            notebook_id="notebook:n1",
            question="What is a monad?",
            answer="A monad is a monoid in the category of endofunctors.",
            message_id="ai-1",
        )
    )

    assert result.success is True
    assert result.exchange_id == "chat_exchange:new1"
    assert result.gist_used_fallback is False
    mock_embed.assert_awaited_once()
    embed_text = mock_embed.await_args.args[0]
    assert "A tidy gist." in embed_text
    mock_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_mirror_chat_exchange_gist_failure_still_creates_and_embeds_row(
    monkeypatch,
):
    """The hard requirement: a gist error must not lose the exchange."""
    answer = "The full assistant answer, which becomes the fallback gist source."
    _patch_gist_pipeline(
        monkeypatch, provision_side_effect=RuntimeError("model unavailable")
    )
    monkeypatch.setattr(smc.ChatExchange, "save", _saved_exchange_stub())
    mock_embed = AsyncMock(return_value=[0.4, 0.5])
    monkeypatch.setattr(smc, "generate_embedding", mock_embed)
    mock_query = AsyncMock()
    monkeypatch.setattr(smc, "repo_query", mock_query)
    monkeypatch.setattr(smc, "ensure_record_id", lambda v: v)

    result = await mirror_chat_exchange_command(
        MirrorChatExchangeInput(
            session_id="chat_session:s2",
            scope="source",
            source_id="source:s1",
            question="Explain X",
            answer=answer,
            message_id="ai-2",
            annotation_ids=["source_annotation:a1"],
        )
    )

    assert result.success is True
    assert result.gist_used_fallback is True
    assert result.exchange_id == "chat_exchange:new1"
    mock_embed.assert_awaited_once()
    mock_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_mirror_chat_exchange_empty_answer_fails_without_raising(monkeypatch):
    result = await mirror_chat_exchange_command(
        MirrorChatExchangeInput(
            session_id="chat_session:s3",
            scope="notebook",
            notebook_id="notebook:n1",
            question="q",
            answer="   ",
            message_id="ai-3",
        )
    )

    assert result.success is False
    assert result.error_message is not None


# --- embed_annotation_command ------------------------------------------------


def _annotation_stub(quote=None, note=None, tags=None):
    return SimpleNamespace(quote=quote, note=note, tags=tags or [])


@pytest.mark.asyncio
async def test_embed_annotation_assembles_quote_note_tags(monkeypatch):
    annotation = _annotation_stub(
        quote="the highlighted text", note="my note", tags=["important", "review"]
    )
    monkeypatch.setattr(
        smc.SourceAnnotation, "get", AsyncMock(return_value=annotation)
    )
    mock_embed = AsyncMock(return_value=[0.1, 0.2])
    monkeypatch.setattr(smc, "generate_embedding", mock_embed)
    monkeypatch.setattr(smc, "repo_query", AsyncMock())
    monkeypatch.setattr(smc, "ensure_record_id", lambda v: v)

    result = await embed_annotation_command(
        EmbedAnnotationInput(annotation_id="source_annotation:a1")
    )

    assert result.success is True
    embedded_text = mock_embed.await_args.args[0]
    assert "the highlighted text" in embedded_text
    assert "my note" in embedded_text
    assert "important, review" in embedded_text


@pytest.mark.asyncio
async def test_embed_annotation_empty_text_returns_failure_not_raise(monkeypatch):
    annotation = _annotation_stub(quote=None, note=None, tags=[])
    monkeypatch.setattr(
        smc.SourceAnnotation, "get", AsyncMock(return_value=annotation)
    )
    mock_embed = AsyncMock()
    monkeypatch.setattr(smc, "generate_embedding", mock_embed)

    result = await embed_annotation_command(
        EmbedAnnotationInput(annotation_id="source_annotation:a2")
    )

    assert result.success is False
    assert result.error_message is not None
    mock_embed.assert_not_awaited()


@pytest.mark.asyncio
async def test_embed_annotation_not_found_returns_failure(monkeypatch):
    monkeypatch.setattr(smc.SourceAnnotation, "get", AsyncMock(return_value=None))

    result = await embed_annotation_command(
        EmbedAnnotationInput(annotation_id="source_annotation:missing")
    )

    assert result.success is False
    assert "not found" in result.error_message
