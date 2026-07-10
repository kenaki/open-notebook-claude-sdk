"""Tests for the sources API endpoint."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from open_notebook.config import UPLOADS_FOLDER
from open_notebook.domain.notebook import Source


@pytest.fixture
def client():
    """Create test client after environment variables have been cleared by conftest."""
    from api.main import app

    return TestClient(app)


class TestAsyncSourceAssetPersistence:
    """Tests for #627 - asset is persisted before async processing.

    These tests hit the real create_source endpoint with mocked DB/command
    calls, verifying that the Source saved to the database has the correct
    asset set *before* async processing begins.
    """

    @pytest.mark.asyncio
    @patch("api.routers.sources.create.CommandService.submit_command_job", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Source.add_to_notebook", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Notebook.get", new_callable=AsyncMock)
    async def test_async_link_source_persists_url_asset(
        self, mock_nb_get, mock_add_nb, mock_submit, client
    ):
        """POST /sources with type=link and async_processing=true persists Asset(url=...)."""
        mock_nb_get.return_value = MagicMock()
        mock_submit.return_value = "command:123"

        saved_sources = []

        async def capture_save(self_source):
            saved_sources.append(self_source)
            self_source.id = "source:fake"
            self_source.command = None

        with patch.object(Source, "save", autospec=True, side_effect=capture_save):
            response = client.post(
                "/api/sources",
                data={
                    "type": "link",
                    "url": "https://example.com/article",
                    "notebooks": '["notebook:1"]',
                    "async_processing": "true",
                },
            )

        assert response.status_code == 200
        assert len(saved_sources) >= 1

        source = saved_sources[0]
        assert source.asset is not None
        assert source.asset.url == "https://example.com/article"
        assert source.asset.file_path is None

    @pytest.mark.asyncio
    @patch("api.routers.sources.create.CommandService.submit_command_job", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Source.add_to_notebook", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Notebook.get", new_callable=AsyncMock)
    @patch("api.routers.sources.create.save_uploaded_file", new_callable=AsyncMock)
    async def test_async_upload_source_persists_file_asset(
        self, mock_upload, mock_nb_get, mock_add_nb, mock_submit, client
    ):
        """POST /sources with type=upload and async_processing=true persists Asset(file_path=...)."""
        mock_nb_get.return_value = MagicMock()
        mock_upload.return_value = os.path.join(os.path.abspath(UPLOADS_FOLDER), "video.mp4")
        mock_submit.return_value = "command:123"

        saved_sources = []

        async def capture_save(self_source):
            saved_sources.append(self_source)
            self_source.id = "source:fake"
            self_source.command = None

        with patch.object(Source, "save", autospec=True, side_effect=capture_save):
            response = client.post(
                "/api/sources",
                data={
                    "type": "upload",
                    "notebooks": '["notebook:1"]',
                    "async_processing": "true",
                },
                files={"file": ("video.mp4", b"fake content", "video/mp4")},
            )

        assert response.status_code == 200
        assert len(saved_sources) >= 1

        source = saved_sources[0]
        assert source.asset is not None
        assert source.asset.file_path == os.path.join(os.path.abspath(UPLOADS_FOLDER), "video.mp4")
        assert source.asset.url is None

    @pytest.mark.asyncio
    @patch("api.routers.sources.create.CommandService.submit_command_job", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Source.add_to_notebook", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Notebook.get", new_callable=AsyncMock)
    async def test_async_text_source_has_no_asset(
        self, mock_nb_get, mock_add_nb, mock_submit, client
    ):
        """POST /sources with type=text and async_processing=true has asset=None."""
        mock_nb_get.return_value = MagicMock()
        mock_submit.return_value = "command:123"

        saved_sources = []

        async def capture_save(self_source):
            saved_sources.append(self_source)
            self_source.id = "source:fake"
            self_source.command = None

        with patch.object(Source, "save", autospec=True, side_effect=capture_save):
            response = client.post(
                "/api/sources",
                data={
                    "type": "text",
                    "content": "Some text content",
                    "notebooks": '["notebook:1"]',
                    "async_processing": "true",
                },
            )

        assert response.status_code == 200
        assert len(saved_sources) >= 1

        source = saved_sources[0]
        assert source.asset is None


class TestRetrySourceProcessing:
    """POST /sources/{id}/retry must find a source's notebooks via the reference
    edge's in/out columns, not a non-existent `source` column (#861)."""

    @pytest.mark.asyncio
    @patch("api.routers.sources.create.command_in_flight", new_callable=AsyncMock)
    @patch("api.routers.sources.create.CommandService.submit_command_job", new_callable=AsyncMock)
    @patch("api.routers.sources.create.repo_query", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Source.get", new_callable=AsyncMock)
    async def test_retry_finds_notebooks_and_requeues(
        self, mock_get, mock_repo_query, mock_submit, mock_in_flight, client
    ):
        mock_in_flight.return_value = False
        source = MagicMock()
        source.id = "source:1"
        source.command = None
        source.title = "My source"
        source.topics = []
        source.full_text = None
        source.asset = MagicMock(file_path=None, url="https://example.com/post")
        source.save = AsyncMock()
        source.get_embedded_chunks = AsyncMock(return_value=0)
        mock_get.return_value = source

        # The corrected query returns the linked notebook(s)
        mock_repo_query.return_value = ["notebook:1"]
        # submit_command_job returns str(RecordID), which already includes the
        # "command:" table prefix.
        mock_submit.return_value = "command:123"

        response = client.post("/api/sources/source:1/retry")

        assert response.status_code == 200
        # Regression guard: must query the reference edge by its `in` column
        called_query = mock_repo_query.await_args.args[0]
        assert "WHERE in = $source_id" in called_query
        assert "SELECT VALUE out FROM reference" in called_query
        # Regression guard: command_id must not be double-prefixed
        # (`command:command:…`), which previously raised a 500 on save.
        assert "command:command" not in str(source.command)
        assert str(source.command).count("command:") == 1
        assert str(source.command).startswith("command:")

    @pytest.mark.asyncio
    @patch("api.routers.sources.create.command_in_flight", new_callable=AsyncMock)
    @patch("api.routers.sources.create.repo_query", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Source.get", new_callable=AsyncMock)
    async def test_retry_400_only_when_truly_unlinked(
        self, mock_get, mock_repo_query, mock_in_flight, client
    ):
        mock_in_flight.return_value = False
        source = MagicMock()
        source.id = "source:1"
        source.command = None
        mock_get.return_value = source
        mock_repo_query.return_value = []  # genuinely no notebooks

        response = client.post("/api/sources/source:1/retry")

        assert response.status_code == 400
        assert "not associated with any notebooks" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("api.routers.sources.create.CommandService.submit_command_job", new_callable=AsyncMock)
    @patch("api.routers.sources.create.command_in_flight", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Source.get", new_callable=AsyncMock)
    async def test_retry_rejects_duplicate_while_process_source_in_flight(
        self, mock_get, mock_in_flight, mock_submit, client
    ):
        """A second Retry click must not queue a second full re-parse.

        build_sections is delete-then-rebuild, so two concurrent process_source
        runs race each other's blocks.
        """
        source = MagicMock()
        source.id = "source:1"
        source.command = None
        mock_get.return_value = source
        mock_in_flight.return_value = True  # a process_source row is already live

        response = client.post("/api/sources/source:1/retry")

        assert response.status_code == 409
        assert "already processing" in response.json()["detail"]
        mock_submit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("api.routers.sources.create.command_in_flight", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Source.get", new_callable=AsyncMock)
    async def test_retry_survives_a_failing_status_probe(
        self, mock_get, mock_in_flight, client
    ):
        """A throwing get_status() must not be downgraded into a silent pass.

        It previously sat inside a bare `except Exception` alongside the
        already-processing HTTPException, so the guard could never fire.
        """
        source = MagicMock()
        source.id = "source:1"
        source.command = "command:old"
        source.get_status = AsyncMock(side_effect=RuntimeError("db down"))
        mock_get.return_value = source
        mock_in_flight.return_value = False

        with patch("api.routers.sources.create.repo_query", new_callable=AsyncMock) as q:
            q.return_value = []  # no notebooks -> 400, proving we got past the probe
            response = client.post("/api/sources/source:1/retry")

        assert response.status_code == 400
        assert "not associated with any notebooks" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("api.routers.sources.create.command_in_flight", new_callable=AsyncMock)
    @patch("api.routers.sources.create.Source.get", new_callable=AsyncMock)
    async def test_retry_rejects_when_status_probe_reports_running(
        self, mock_get, mock_in_flight, client
    ):
        source = MagicMock()
        source.id = "source:1"
        source.command = "command:old"
        source.get_status = AsyncMock(return_value="running")
        mock_get.return_value = source
        mock_in_flight.return_value = False  # force the probe to be the guard

        response = client.post("/api/sources/source:1/retry")

        assert response.status_code == 409
        assert "already processing" in response.json()["detail"]


class TestSubmitSourceCommandLinkBack:
    """A submitted command row is live immediately; the link-back must not leak it."""

    @pytest.mark.asyncio
    async def test_tx_conflict_on_link_is_retried(self):
        from api.routers.sources.create import _submit_source_command

        source = MagicMock()
        source.id = "source:1"
        # First save loses the optimistic-concurrency check, second wins.
        source.save = AsyncMock(
            side_effect=[
                Exception("Failed to commit transaction due to a read or write conflict"),
                None,
            ]
        )

        with patch(
            "api.routers.sources.create.CommandService.submit_command_job",
            new_callable=AsyncMock,
        ) as submit:
            submit.return_value = "command:123"
            command_id = await _submit_source_command(source, {}, ["notebook:1"], [], True)

        assert command_id == "command:123"
        assert source.save.await_count == 2

    @pytest.mark.asyncio
    async def test_unrecoverable_link_failure_cancels_the_queued_job(self):
        """Otherwise the caller sees 'failed to queue' while the job runs anyway."""
        from api.routers.sources.create import _submit_source_command

        source = MagicMock()
        source.id = "source:1"
        source.save = AsyncMock(side_effect=ValueError("schema exploded"))

        with (
            patch(
                "api.routers.sources.create.CommandService.submit_command_job",
                new_callable=AsyncMock,
            ) as submit,
            patch(
                "api.routers.sources.create.CommandService.cancel_command_job",
                new_callable=AsyncMock,
            ) as cancel,
        ):
            submit.return_value = "command:123"
            with pytest.raises(ValueError):
                await _submit_source_command(source, {}, ["notebook:1"], [], True)

        cancel.assert_awaited_once_with("command:123")


class TestGetSourceNotFound:
    """GET /sources/{id} must return 404 (not 500) for a missing/deleted source.
    `Source.get()` raises NotFoundError rather than returning None, so the handler
    must map it to 404 instead of catching it in its generic `except`."""

    @pytest.mark.asyncio
    @patch("api.routers.sources.crud.Source.get", new_callable=AsyncMock)
    async def test_get_missing_source_returns_404(self, mock_get, client):
        from open_notebook.exceptions import NotFoundError

        mock_get.side_effect = NotFoundError("source with id source:gone not found")

        response = client.get("/api/sources/source:gone")

        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
