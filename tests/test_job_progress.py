from unittest.mock import AsyncMock

import pytest

from open_notebook.utils import job_progress


def _patch_repo_query(monkeypatch, mock=None):
    """append_job_event/report_job_progress import `repo_query`/`ensure_record_id`
    lazily from `open_notebook.database.repository` inside the try block, so we
    patch the source module's attributes (not job_progress's namespace).
    """
    mock_query = mock or AsyncMock(return_value=[{"id": "command:abc123"}])
    monkeypatch.setattr(
        "open_notebook.database.repository.repo_query", mock_query
    )
    return mock_query


@pytest.mark.asyncio
async def test_append_job_event_noop_without_job_id(monkeypatch):
    mock_query = _patch_repo_query(monkeypatch)

    await job_progress.append_job_event(None, "phase", phase="Starting")

    mock_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_append_job_event_statement_shape_and_cap(monkeypatch):
    mock_query = _patch_repo_query(monkeypatch)

    await job_progress.append_job_event(
        "command:abc123", "tool_call", tool_name="search_sources", tool_input={"q": "x"}
    )

    mock_query.assert_awaited_once()
    query_str, query_vars = mock_query.await_args.args

    # Single statement, uses array::concat (not `+` — rejected by this
    # SurrealDB build per the live probe) + negative-start array::slice,
    # capped at 200 total events (keep newest 199, append 1 new).
    assert "array::concat(" in query_str
    assert "array::slice(progress.events ?? [], -199)" in query_str
    assert "progress.events = " in query_str

    # tool_name/tool_input are additionally stamped at the top level
    # (back-compat with existing tray/live-label consumers).
    assert "progress.tool_name = $tool_name" in query_str
    assert "progress.tool_input = $tool_input" in query_str
    assert query_vars["tool_name"] == "search_sources"
    assert query_vars["tool_input"] == {"q": "x"}

    # Event payload is a plain-JSON dict: iso8601 "t", "type", and the extra
    # payload fields — no RecordID/datetime objects.
    event = query_vars["event"]
    assert event["type"] == "tool_call"
    assert event["tool_name"] == "search_sources"
    assert event["tool_input"] == {"q": "x"}
    assert isinstance(event["t"], str)
    assert "T" in event["t"]  # iso8601


@pytest.mark.asyncio
async def test_append_job_event_no_tool_fields_no_extra_clauses(monkeypatch):
    mock_query = _patch_repo_query(monkeypatch)

    await job_progress.append_job_event("command:abc123", "context", chars=123)

    query_str, query_vars = mock_query.await_args.args
    assert "progress.tool_name" not in query_str
    assert "progress.tool_input" not in query_str
    assert "progress.phase" not in query_str
    assert "tool_name" not in query_vars
    assert "tool_input" not in query_vars
    assert "phase" not in query_vars


@pytest.mark.asyncio
async def test_append_job_event_swallows_db_errors(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db is down")

    _patch_repo_query(monkeypatch, AsyncMock(side_effect=boom))

    # Must not raise — progress reporting is best-effort.
    await job_progress.append_job_event("command:abc123", "phase", phase="Extracting")


@pytest.mark.asyncio
async def test_report_job_progress_delegates_to_append_job_event(monkeypatch):
    mock_append = AsyncMock()
    monkeypatch.setattr(job_progress, "append_job_event", mock_append)

    await job_progress.report_job_progress(
        "command:abc123", "Using search_sources", tool_name="search_sources", tool_input={"q": "x"}
    )

    mock_append.assert_awaited_once_with(
        "command:abc123",
        "phase",
        phase="Using search_sources",
        label="Using search_sources",
        tool_name="search_sources",
        tool_input={"q": "x"},
    )


@pytest.mark.asyncio
async def test_report_job_progress_noop_without_job_id(monkeypatch):
    mock_query = _patch_repo_query(monkeypatch)

    await job_progress.report_job_progress(None, "Extracting text")

    mock_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_append_job_event_sets_phase_when_given(monkeypatch):
    mock_query = _patch_repo_query(monkeypatch)

    await job_progress.append_job_event("command:abc123", "phase", phase="Saving & indexing")

    query_str, query_vars = mock_query.await_args.args
    assert "progress.phase = $phase" in query_str
    assert query_vars["phase"] == "Saving & indexing"
