"""Unit tests for the reverse citing-sessions / citing-counts lookups
(cross-interface-study B2).

Covers the pure classification helper and response-model shapes in
``api.routers.sources.annotations`` on synthetic rows — no DB, no live app.
Mirrors ``tests/test_chat_annotation_refs.py``.

- ``_classify_citing_sessions``: joins session rows with `refers_to` scope
  edges, classifies notebook vs. source scope, skips orphan sessions
  (Q-orphan-sessions), orders by `updated` desc.
- ``CitingSessionResponse`` / ``CitingCountsResponse``: response-model shape.
"""

from api.routers.sources.annotations import (
    CitingCountsResponse,
    CitingSessionResponse,
    _classify_citing_sessions,
)

# --- _classify_citing_sessions ------------------------------------------------


def test_classify_notebook_scope():
    session_rows = [
        {"id": "chat_session:s1", "title": "My chat", "updated": "2026-07-10T10:00:00Z"}
    ]
    refers_rows = [{"in": "chat_session:s1", "out": "notebook:nb1"}]

    result = _classify_citing_sessions(session_rows, refers_rows)

    assert len(result) == 1
    item = result[0]
    assert item.session_id == "chat_session:s1"
    assert item.scope == "notebook"
    assert item.notebook_id == "notebook:nb1"
    assert item.source_id is None
    assert item.title == "My chat"
    assert item.updated == "2026-07-10T10:00:00Z"


def test_classify_source_scope():
    session_rows = [{"id": "chat_session:s2", "title": None, "updated": None}]
    refers_rows = [{"in": "chat_session:s2", "out": "source:src1"}]

    result = _classify_citing_sessions(session_rows, refers_rows)

    assert len(result) == 1
    item = result[0]
    assert item.scope == "source"
    assert item.source_id == "source:src1"
    assert item.notebook_id is None
    # Missing title falls back to a friendly default.
    assert item.title == "Untitled Session"
    assert item.updated is None


def test_classify_skips_orphan_session_with_no_refers_to_edge():
    """Q-orphan-sessions: a citing session with no refers_to edge is SKIPPED
    (the simpler option — no third "unknown" scope value to carry)."""
    session_rows = [
        {"id": "chat_session:orphan", "title": "Orphaned", "updated": "2026-01-01"}
    ]
    refers_rows: list = []

    result = _classify_citing_sessions(session_rows, refers_rows)

    assert result == []


def test_classify_skips_unrecognized_scope_prefix():
    session_rows = [{"id": "chat_session:s3", "title": "Weird", "updated": None}]
    refers_rows = [{"in": "chat_session:s3", "out": "notebook_group:g1"}]

    result = _classify_citing_sessions(session_rows, refers_rows)

    assert result == []


def test_classify_orders_by_updated_desc():
    session_rows = [
        {"id": "chat_session:old", "title": "Old", "updated": "2026-01-01T00:00:00Z"},
        {"id": "chat_session:new", "title": "New", "updated": "2026-07-10T00:00:00Z"},
    ]
    refers_rows = [
        {"in": "chat_session:old", "out": "notebook:nb1"},
        {"in": "chat_session:new", "out": "notebook:nb1"},
    ]

    result = _classify_citing_sessions(session_rows, refers_rows)

    assert [item.session_id for item in result] == [
        "chat_session:new",
        "chat_session:old",
    ]


def test_classify_ignores_refers_rows_with_missing_fields():
    session_rows = [{"id": "chat_session:s4", "title": "T", "updated": None}]
    refers_rows = [{"in": None, "out": "notebook:nb1"}, {"in": "chat_session:s4"}]

    result = _classify_citing_sessions(session_rows, refers_rows)

    assert result == []


# --- response model shapes ----------------------------------------------------


def test_citing_session_response_shape_notebook():
    item = CitingSessionResponse(
        session_id="chat_session:s1",
        title="My chat",
        scope="notebook",
        notebook_id="notebook:nb1",
        source_id=None,
        updated="2026-07-10T10:00:00Z",
    )
    dumped = item.model_dump()
    assert dumped == {
        "session_id": "chat_session:s1",
        "title": "My chat",
        "scope": "notebook",
        "notebook_id": "notebook:nb1",
        "source_id": None,
        "updated": "2026-07-10T10:00:00Z",
    }


def test_citing_session_response_optional_fields_default_none():
    item = CitingSessionResponse(session_id="chat_session:s1", title="T", scope="source")
    assert item.notebook_id is None
    assert item.source_id is None
    assert item.updated is None


def test_citing_counts_response_shape():
    resp = CitingCountsResponse(counts={"source_annotation:a1": 2, "source_annotation:a2": 0})
    assert resp.model_dump() == {
        "counts": {"source_annotation:a1": 2, "source_annotation:a2": 0}
    }


def test_citing_counts_response_empty():
    resp = CitingCountsResponse(counts={})
    assert resp.counts == {}
