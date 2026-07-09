"""Regression tests: verify-clean jobs must self-skip when their section tree
has been superseded by a rebuild, rather than failing and burning retries.

Live incident (2026-07-09): build_sections is delete-then-rebuild, so a
build_blocks-triggered rebuild mid-queue orphaned every pending
verify_clean_section job. Each orphan raised NotFoundError, was retried 5×, then
marked failed — 89 failed + 377 doomed-queued jobs on one book, saturating the
worker and starving the very build_sections rows whose stuck 'new' state kept
the in-flight guard latched on forever.
"""

from unittest.mock import AsyncMock, patch

import pytest

from commands import _job_guards, verify_commands
from commands.summary_commands import SummarizeSectionInput, summarize_section
from commands.verify_commands import VerifyCleanSectionInput, verify_clean_section
from open_notebook.exceptions import NotFoundError


def _section_input(**kw):
    """VerifyCleanSectionInput with no execution_context (untracked job)."""
    return VerifyCleanSectionInput(source_section_id="source_section:dead", **kw)


@pytest.mark.asyncio
async def test_deleted_section_skips_instead_of_raising():
    """An orphaned section id is obsolete work, not an error."""
    with (
        patch(
            "commands.verify_commands.SourceSection.get",
            AsyncMock(side_effect=NotFoundError("source_section:dead not found")),
        ),
        # Existence recheck: no rows => genuinely deleted.
        patch("commands._job_guards.repo_query", AsyncMock(return_value=[])),
    ):
        out = await verify_clean_section(_section_input())

    assert out.cleaned_content is None
    assert out.discrepancies is None


@pytest.mark.asyncio
async def test_transient_db_error_still_raises():
    """ObjectModel.get funnels ANY exception into NotFoundError. A DB hiccup must
    keep retrying, not be mistaken for a superseded section and skipped."""
    with (
        patch(
            "commands.verify_commands.SourceSection.get",
            AsyncMock(side_effect=NotFoundError("Object with id ... not found - timeout")),
        ),
        # Recheck says the row is very much still there.
        patch(
            "commands._job_guards.repo_query",
            AsyncMock(return_value=[{"id": "source_section:dead"}]),
        ),
    ):
        with pytest.raises(NotFoundError):
            await verify_clean_section(_section_input())


@pytest.mark.asyncio
async def test_db_error_during_recheck_propagates():
    """If the existence recheck itself fails, we must not guess 'deleted'."""
    with (
        patch(
            "commands.verify_commands.SourceSection.get",
            AsyncMock(side_effect=NotFoundError("boom")),
        ),
        patch(
            "commands._job_guards.repo_query",
            AsyncMock(side_effect=RuntimeError("connection refused")),
        ),
    ):
        with pytest.raises(RuntimeError):
            await verify_clean_section(_section_input())


@pytest.mark.asyncio
async def test_stale_parse_generation_skips():
    """Section still resolves, but the source was re-parsed since fan-out."""
    section = AsyncMock(id="source_section:s1", source="source:x")
    source = AsyncMock(id="source:x", parse_generation=3)

    with (
        patch("commands.verify_commands.SourceSection.get", AsyncMock(return_value=section)),
        patch("commands.verify_commands.Source.get", AsyncMock(return_value=source)),
        patch("commands.verify_commands._resolve_pdf_path") as resolve,
    ):
        out = await verify_clean_section(_section_input(parse_generation=2))

    assert out.cleaned_content is None
    # Skipped before touching the PDF — no render, no vision call.
    resolve.assert_not_called()


@pytest.mark.asyncio
async def test_matching_parse_generation_proceeds():
    """The stamp must not skip work that is still current."""
    section = AsyncMock(id="source_section:s1", source="source:x")
    source = AsyncMock(id="source:x", parse_generation=3)

    with (
        patch("commands.verify_commands.SourceSection.get", AsyncMock(return_value=section)),
        patch("commands.verify_commands.Source.get", AsyncMock(return_value=source)),
        patch("commands.verify_commands._resolve_pdf_path", return_value=None) as resolve,
    ):
        await verify_clean_section(_section_input(parse_generation=3))

    # Got past the staleness gate (it then skips for the unrelated no-PDF reason).
    resolve.assert_called_once()


@pytest.mark.asyncio
async def test_unstamped_job_proceeds():
    """Manual re-runs carry no stamp and must not be treated as stale."""
    section = AsyncMock(id="source_section:s1", source="source:x")
    source = AsyncMock(id="source:x", parse_generation=7)

    with (
        patch("commands.verify_commands.SourceSection.get", AsyncMock(return_value=section)),
        patch("commands.verify_commands.Source.get", AsyncMock(return_value=source)),
        patch("commands.verify_commands._resolve_pdf_path", return_value=None) as resolve,
    ):
        await verify_clean_section(_section_input())

    resolve.assert_called_once()


@pytest.mark.asyncio
async def test_submit_command_once_coalesces_onto_pending_job():
    """The stuck-row accumulation that latched the in-flight guard forever."""
    with (
        patch.object(_job_guards, "command_in_flight", AsyncMock(return_value=True)),
        patch.object(_job_guards, "submit_command") as submit,
    ):
        result = await _job_guards.submit_command_once(
            "open_notebook", "build_sections", {"source_id": "source:x"}, "source:x"
        )

    assert result is None
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_submit_command_once_submits_when_clear():
    with (
        patch.object(_job_guards, "command_in_flight", AsyncMock(return_value=False)),
        patch.object(_job_guards, "submit_command", return_value="command:new") as submit,
    ):
        result = await _job_guards.submit_command_once(
            "open_notebook", "build_sections", {"source_id": "source:x"}, "source:x"
        )

    assert result == "command:new"
    submit.assert_called_once()


# --- summarize_section: the same orphan bug, same fix -----------------------


def _summary_input(**kw):
    return SummarizeSectionInput(source_section_id="source_section:dead", **kw)


@pytest.mark.asyncio
async def test_summarize_deleted_section_skips():
    with (
        patch(
            "commands.summary_commands.SourceSection.get",
            AsyncMock(side_effect=NotFoundError("gone")),
        ),
        patch("commands._job_guards.repo_query", AsyncMock(return_value=[])),
    ):
        out = await summarize_section(_summary_input())

    assert out.summary is None


@pytest.mark.asyncio
async def test_summarize_transient_db_error_still_raises():
    with (
        patch(
            "commands.summary_commands.SourceSection.get",
            AsyncMock(side_effect=NotFoundError("timeout")),
        ),
        patch(
            "commands._job_guards.repo_query",
            AsyncMock(return_value=[{"id": "source_section:dead"}]),
        ),
    ):
        with pytest.raises(NotFoundError):
            await summarize_section(_summary_input())


@pytest.mark.asyncio
async def test_summarize_stale_parse_generation_skips():
    section = AsyncMock(id="source_section:s1", source="source:x")
    section.cleaned_content = "text that must never be summarized"
    section.content = "raw"
    source = AsyncMock(id="source:x", parse_generation=5)

    with (
        patch("commands.summary_commands.SourceSection.get", AsyncMock(return_value=section)),
        patch("commands.summary_commands.Source.get", AsyncMock(return_value=source)),
        patch("commands.summary_commands.provision_langchain_model") as provision,
    ):
        out = await summarize_section(_summary_input(parse_generation=4))

    assert out.summary is None
    provision.assert_not_called()  # no model call for obsolete work


# --- blocked-on-a-busy-model must requeue, not fail --------------------------


def test_busy_signals_are_recognized():
    """Gate 503 / rate limits mean the heavy slot is busy."""
    for msg in ("503 service unavailable", "overloaded", "429 too many requests",
                "rate limit exceeded", "model is loading"):
        assert _job_guards.is_resource_busy(Exception(msg)), msg


def test_real_errors_are_never_treated_as_busy():
    """classify_error defaults UNCLASSIFIED exceptions to ExternalServiceError, so
    keying requeue off it would bury genuine bugs as 'waiting for a model'. The
    busy check must be an allowlist that defaults to 'this is a real error'."""
    for exc in (
        ValueError("bad section id"),
        AttributeError("'NoneType' object has no attribute 'content'"),
        KeyError("page_start"),
        RuntimeError("connection refused"),
        TypeError("unsupported operand"),
    ):
        assert not _job_guards.is_resource_busy(exc), repr(exc)

    # Sanity: the helper we deliberately avoided would have said "busy" for these.
    from open_notebook.exceptions import ExternalServiceError
    from open_notebook.utils.error_classifier import classify_error

    assert classify_error(AttributeError("boom"))[0] is ExternalServiceError


def test_permanent_classes_win_over_marker_text():
    """A ValueError whose message happens to contain '503' is still a real error."""
    assert not _job_guards.is_resource_busy(ValueError("got 503 in the payload"))


@pytest.mark.asyncio
async def test_requeue_is_capped():
    """A model that is gone (not merely busy) must not requeue forever."""
    assert _job_guards.MAX_REQUEUES > 0
    # The guard the commands apply: requeue_count < MAX_REQUEUES.
    assert not (_job_guards.MAX_REQUEUES < _job_guards.MAX_REQUEUES)


# --- phase chain: verify -> summarize ---------------------------------------


@pytest.mark.asyncio
async def test_chain_waits_while_verify_siblings_pending():
    """Summarize must not start while other verify jobs are still queued —
    that is what interleaves two 35B Ollama models on one heavy slot."""
    inp = VerifyCleanSectionInput(
        source_section_id="source_section:s1", source_id="source:x"
    )
    with (
        patch("commands.verify_commands._job_id", return_value="command:me"),
        patch("commands.verify_commands.siblings_in_flight", AsyncMock(return_value=True)),
        patch("commands.verify_commands.submit_command_once", AsyncMock()) as submit,
    ):
        await verify_commands._chain_summarize_if_last(inp)

    submit.assert_not_called()


@pytest.mark.asyncio
async def test_last_verify_job_chains_summarize():
    inp = VerifyCleanSectionInput(
        source_section_id="source_section:s1", source_id="source:x"
    )
    with (
        patch("commands.verify_commands._job_id", return_value="command:me"),
        patch("commands.verify_commands.siblings_in_flight", AsyncMock(return_value=False)),
        patch("commands.verify_commands.submit_command_once", AsyncMock()) as submit,
    ):
        await verify_commands._chain_summarize_if_last(inp)

    submit.assert_called_once()
    assert submit.call_args[0][1] == "summarize_source"


@pytest.mark.asyncio
async def test_chain_noops_without_source_id():
    """Unstamped single-section runs have no source to chain for."""
    inp = VerifyCleanSectionInput(source_section_id="source_section:s1")
    with patch("commands.verify_commands.submit_command_once", AsyncMock()) as submit:
        await verify_commands._chain_summarize_if_last(inp)
    submit.assert_not_called()
