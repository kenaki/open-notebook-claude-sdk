from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from surreal_commands import registry

import commands
import commands.embedding_commands as embedding_commands


def _patch_common(monkeypatch, source, events, inserted):
    """Wire the shared mocks embed_source_command needs and record DB call order.

    *events* accumulates 'insert' / 'delete' markers in call order; *inserted*
    accumulates the record lists passed to repo_insert.
    """
    monkeypatch.setattr(
        embedding_commands.Source, "get", AsyncMock(return_value=source)
    )
    monkeypatch.setattr(
        embedding_commands, "generate_embeddings", AsyncMock(return_value=[[0.1, 0.2]])
    )
    monkeypatch.setattr(embedding_commands, "ensure_record_id", lambda v: v)
    monkeypatch.setattr(embedding_commands, "repo_update", AsyncMock())

    async def fake_insert(table, records, *a, **k):
        events.append("insert")
        inserted.append(records)
        return records

    async def fake_query(query, params=None):
        q = query.strip().upper()
        if q.startswith("DELETE"):
            events.append("delete")
        return []

    monkeypatch.setattr(embedding_commands, "repo_insert", fake_insert)
    monkeypatch.setattr(embedding_commands, "repo_query", fake_query)


def test_legacy_embedding_commands_are_registered():
    app_commands = registry.list_commands()["open_notebook"]

    assert "embed_chunk" in app_commands
    assert "embed_single_item" in app_commands
    assert "vectorize_source" in app_commands


@pytest.mark.asyncio
async def test_legacy_embed_chunk_processes_stale_queue_payload(monkeypatch):
    mock_generate_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3])
    mock_repo_query = AsyncMock()

    monkeypatch.setattr(
        embedding_commands, "generate_embedding", mock_generate_embedding
    )
    monkeypatch.setattr(embedding_commands, "repo_query", mock_repo_query)
    monkeypatch.setattr(
        embedding_commands, "ensure_record_id", lambda value: f"record:{value}"
    )

    result = await embedding_commands.legacy_embed_chunk_command(
        embedding_commands.LegacyEmbedChunkInput(
            source_id="source:abc",
            chunk_index=2,
            chunk_text="queued legacy chunk",
        )
    )

    assert result.success is True
    assert result.source_id == "source:abc"
    assert result.chunk_index == 2
    mock_generate_embedding.assert_awaited_once_with(
        "queued legacy chunk",
        content_type=embedding_commands.ContentType.PLAIN,
        command_id="unknown",
    )
    mock_repo_query.assert_awaited_once()
    assert mock_repo_query.await_args is not None
    assert mock_repo_query.await_args.args[1] == {
        "source_id": "record:source:abc",
        "order": 2,
        "content": "queued legacy chunk",
        "embedding": [0.1, 0.2, 0.3],
    }


@pytest.mark.asyncio
async def test_embed_source_legacy_inserts_before_delete(monkeypatch):
    """No-blackout ordering: new rows INSERTed before stale rows DELETEd (B4)."""
    source = SimpleNamespace(
        id="source:abc",
        full_text="hello world",
        asset=None,
        page_map=None,
        parse_generation=None,
        parse_status="embedding",
    )
    events: list[str] = []
    inserted: list = []
    _patch_common(monkeypatch, source, events, inserted)

    result = await embedding_commands.embed_source_command(
        embedding_commands.EmbedSourceInput(source_id="source:abc")
    )

    assert result.success is True
    # INSERT happens before DELETE — kills the re-embed blackout window.
    assert "insert" in events and "delete" in events
    assert events.index("insert") < events.index("delete")
    # Legacy rows still carry a monotonic gen (=1 for a first embed).
    assert inserted[0][0]["gen"] == 1


@pytest.mark.asyncio
async def test_embed_source_block_path_records_ranges(monkeypatch):
    """Block path packs blocks, stamps block_start/block_end/gen/page_number."""
    source = SimpleNamespace(
        id="source:xyz",
        full_text="regenerated markdown",
        asset=None,
        page_map=None,
        parse_generation=2,
        parse_status="embedding",
    )
    events: list[str] = []
    inserted: list = []
    _patch_common(monkeypatch, source, events, inserted)
    # 3 block chunks -> 3 embeddings
    monkeypatch.setattr(
        embedding_commands,
        "generate_embeddings",
        AsyncMock(return_value=[[0.1], [0.2], [0.3]]),
    )
    monkeypatch.setattr(
        embedding_commands.blocks,
        "get_parse_header",
        AsyncMock(return_value=SimpleNamespace(status="ready", block_count=3)),
    )
    block_rows = [
        {"seq": 0, "page": 1, "type": "paragraph", "text": "Alpha."},
        {"seq": 1, "page": 1, "type": "equation", "latex": "x^2"},
        {"seq": 2, "page": 2, "type": "paragraph", "text": "Beta."},
    ]
    monkeypatch.setattr(
        embedding_commands.blocks, "get_range", AsyncMock(return_value=block_rows)
    )

    result = await embedding_commands.embed_source_command(
        embedding_commands.EmbedSourceInput(source_id="source:xyz")
    )

    assert result.success is True
    assert result.chunks_created == 3
    recs = inserted[0]
    assert [r["block_start"] for r in recs] == [0, 1, 2]
    assert [r["block_end"] for r in recs] == [0, 1, 2]
    assert all(r["gen"] == 2 for r in recs)
    assert recs[2]["page_number"] == 2
    assert recs[1]["content"] == "$$\nx^2\n$$"
    # ordering still holds on the block path
    assert events.index("insert") < events.index("delete")


@pytest.mark.asyncio
async def test_legacy_vectorize_source_delegates_to_embed_source(monkeypatch):
    async def fake_embed_source(input_data):
        assert input_data.source_id == "source:abc"
        return embedding_commands.EmbedSourceOutput(
            success=True,
            source_id=input_data.source_id,
            chunks_created=3,
            processing_time=0.1,
        )

    monkeypatch.setattr(embedding_commands, "embed_source_command", fake_embed_source)

    result = await embedding_commands.legacy_vectorize_source_command(
        embedding_commands.LegacyVectorizeSourceInput(source_id="source:abc")
    )

    assert result.success is True
    assert result.source_id == "source:abc"
    assert result.total_chunks == 3
    assert result.jobs_submitted == 1


@pytest.mark.asyncio
async def test_legacy_embed_single_item_routes_insights(monkeypatch):
    async def fake_embed_insight(input_data):
        assert input_data.insight_id == "source_insight:abc"
        return embedding_commands.EmbedInsightOutput(
            success=True,
            insight_id=input_data.insight_id,
            processing_time=0.1,
        )

    monkeypatch.setattr(embedding_commands, "embed_insight_command", fake_embed_insight)

    result = await embedding_commands.legacy_embed_single_item_command(
        embedding_commands.LegacyEmbedSingleItemInput(
            item_id="source_insight:abc",
            item_type="insight",
        )
    )

    assert result.success is True
    assert result.item_id == "source_insight:abc"
    assert result.item_type == "insight"
    assert result.chunks_created == 0
