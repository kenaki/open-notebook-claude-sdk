from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.command_service as command_service
from api.command_service import CommandService


def test_strip_events_removes_events_key():
    progress = {"phase": "Extracting text", "events": [{"t": "x", "type": "phase"}]}

    stripped = CommandService._strip_events(progress)

    assert stripped == {"phase": "Extracting text"}
    assert "events" not in stripped


def test_strip_events_passthrough_when_no_events_key():
    progress = {"phase": "Extracting text"}

    assert CommandService._strip_events(progress) == progress


def test_strip_events_passthrough_for_none_and_non_dict():
    assert CommandService._strip_events(None) is None
    assert CommandService._strip_events("not-a-dict") == "not-a-dict"


@pytest.mark.asyncio
async def test_list_command_jobs_strips_events_from_progress(monkeypatch):
    rows = [
        {
            "id": "command:abc123",
            "name": "process_source",
            "status": "running",
            "result": None,
            "error_message": None,
            "created": None,
            "updated": None,
            "args": {"source_id": "source:1"},
            "progress": {
                "phase": "Extracting text",
                "events": [{"t": "now", "type": "phase", "label": "Extracting text"}],
            },
        }
    ]
    monkeypatch.setattr(
        "open_notebook.database.repository.repo_query", AsyncMock(return_value=rows)
    )

    result = await CommandService.list_command_jobs()

    assert len(result) == 1
    assert result[0]["progress"] == {"phase": "Extracting text"}
    assert "events" not in result[0]["progress"]


@pytest.mark.asyncio
async def test_get_command_status_returns_full_events_and_args(monkeypatch):
    fake_status = SimpleNamespace(
        status="running",
        result=None,
        error_message=None,
        created=None,
        updated=None,
    )
    monkeypatch.setattr(
        command_service, "get_command_status", AsyncMock(return_value=fake_status)
    )
    detail_progress = {
        "phase": "Extracting text",
        "events": [{"t": "now", "type": "phase", "label": "Extracting text"}],
    }
    monkeypatch.setattr(
        "open_notebook.database.repository.repo_query",
        AsyncMock(
            return_value=[{"progress": detail_progress, "args": {"source_id": "source:1"}}]
        ),
    )

    status = await CommandService.get_command_status("command:abc123")

    # Detail fetch keeps events[] (console reads this directly) and surfaces args.
    assert status["progress"] == detail_progress
    assert "events" in status["progress"]
    assert status["args"] == {"source_id": "source:1"}
