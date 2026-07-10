"""Unit tests for study-memory recall search (Track B, chunk B1).

Covers `open_notebook.domain.recall`:
  * `recall_search` — normalization (contract keys + RecordID stringification),
    dedupe (highest similarity wins per session_id/annotation_id), and cap at
    `limit` — against a **mocked** `repo_query`/`generate_embedding` (no DB).
  * `dedupe_and_cap_recall_refs` in isolation.
  * `get_exchange_content` — dispatch on id prefix, mocked `repo_query`.

Also the STRUCTURAL spoiler-guard test (coordinator decision 5): the JSON
`search_past_discussions` (chat_tools.py) returns must never contain `gist`
or `note` — that's the whole point of the two-tool split.
"""

import json

import pytest
from surrealdb import RecordID

from open_notebook.ai import chat_tools
from open_notebook.domain import recall
from open_notebook.domain.recall import (
    _MAX_RECALL_REFS,
    _RECALL_REF_FIELDS,
    dedupe_and_cap_recall_refs,
    get_exchange_content,
    recall_search,
)


def _raw_row(**overrides):
    """One raw fn::recall_search row, RecordID-shaped where the fn would link
    a record, contract-shaped keys otherwise. Overrides replace defaults."""
    base = dict(
        id=RecordID("chat_exchange", "e0"),
        kind="exchange",
        session_id=RecordID("chat_session", "s0"),
        title="Some session",
        scope="notebook",
        source_id=None,
        notebook_id=RecordID("notebook", "nb0"),
        message_id="ai-0",
        annotation_id=None,
        page=None,
        quote="a question",
        similarity=0.5,
    )
    base.update(overrides)
    return base


# --- recall_search: normalization + dedupe + cap (mocked repo_query) --------


@pytest.fixture
def mock_recall_backend(monkeypatch):
    """Patch generate_embedding + repo_query so recall_search never touches a
    real DB/embedding model. Returns a mutable holder so tests can set the
    rows repo_query will "return"."""
    calls = {"embed_query": None, "repo_query_vars": None}

    async def fake_generate_embedding(text, *args, **kwargs):
        calls["embed_query"] = text
        return [0.1, 0.2, 0.3]

    holder = {"rows": []}

    async def fake_repo_query(query_str, variables=None):
        calls["repo_query_vars"] = variables
        return holder["rows"]

    monkeypatch.setattr(recall, "generate_embedding", fake_generate_embedding)
    monkeypatch.setattr(recall, "repo_query", fake_repo_query)
    return holder, calls


@pytest.mark.asyncio
async def test_recall_search_embeds_query_and_passes_params(mock_recall_backend):
    holder, calls = mock_recall_backend
    holder["rows"] = []

    await recall_search("what is a monad", limit=7, minimum_score=0.4)

    assert calls["embed_query"] == "what is a monad"
    assert calls["repo_query_vars"]["match_count"] == 7
    assert calls["repo_query_vars"]["min_similarity"] == 0.4
    assert calls["repo_query_vars"]["query"] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_recall_search_normalizes_every_contract_key(mock_recall_backend):
    holder, _ = mock_recall_backend
    # A minimal-ish row missing several optional fields entirely (as a real
    # NONE-heavy annotation row might collapse when the driver omits keys
    # rather than sending explicit nulls).
    holder["rows"] = [
        {
            "id": RecordID("source_annotation", "a1"),
            "kind": "annotation",
            "source_id": RecordID("source", "src1"),
            "annotation_id": RecordID("source_annotation", "a1"),
            "quote": "highlighted text",
            "similarity": 0.6,
        }
    ]

    results = await recall_search("query")

    assert len(results) == 1
    ref = results[0]
    # Every contract key present, even ones the raw row never mentioned.
    for field in _RECALL_REF_FIELDS:
        assert field in ref
    assert ref["title"] is None
    assert ref["session_id"] is None
    assert ref["notebook_id"] is None
    assert ref["message_id"] is None
    # RecordID-shaped fields are stringified.
    assert ref["source_id"] == "source:src1"
    assert ref["annotation_id"] == "source_annotation:a1"
    assert isinstance(ref["source_id"], str)


@pytest.mark.asyncio
async def test_recall_search_dedupes_by_session_id_keeping_highest_similarity(
    mock_recall_backend,
):
    holder, _ = mock_recall_backend
    holder["rows"] = [
        _raw_row(id=RecordID("chat_exchange", "e1"), session_id=RecordID("chat_session", "s1"), similarity=0.55),
        # Same session, HIGHER similarity — should win.
        _raw_row(id=RecordID("chat_exchange", "e2"), session_id=RecordID("chat_session", "s1"), similarity=0.91),
        # Same session, lower again — should be dropped.
        _raw_row(id=RecordID("chat_exchange", "e3"), session_id=RecordID("chat_session", "s1"), similarity=0.60),
        # Different session — kept as its own entry.
        _raw_row(id=RecordID("chat_exchange", "e4"), session_id=RecordID("chat_session", "s2"), similarity=0.70),
    ]

    results = await recall_search("query", limit=10)

    assert len(results) == 2
    by_session = {r["session_id"]: r["similarity"] for r in results}
    assert by_session["chat_session:s1"] == 0.91
    assert by_session["chat_session:s2"] == 0.70


@pytest.mark.asyncio
async def test_recall_search_dedupes_annotations_by_annotation_id(mock_recall_backend):
    holder, _ = mock_recall_backend
    holder["rows"] = [
        _raw_row(
            id=RecordID("source_annotation", "a1"),
            kind="annotation",
            session_id=None,
            scope="source",
            source_id=RecordID("source", "src1"),
            notebook_id=None,
            annotation_id=RecordID("source_annotation", "a1"),
            similarity=0.3,
        ),
        _raw_row(
            id=RecordID("source_annotation", "a1"),
            kind="annotation",
            session_id=None,
            scope="source",
            source_id=RecordID("source", "src1"),
            notebook_id=None,
            annotation_id=RecordID("source_annotation", "a1"),
            similarity=0.8,
        ),
    ]

    results = await recall_search("query")

    assert len(results) == 1
    assert results[0]["similarity"] == 0.8


@pytest.mark.asyncio
async def test_recall_search_caps_at_limit(mock_recall_backend):
    holder, _ = mock_recall_backend
    # 13 distinct sessions (unique dedupe keys) — more than the default cap.
    holder["rows"] = [
        _raw_row(
            id=RecordID("chat_exchange", f"e{i}"),
            session_id=RecordID("chat_session", f"s{i}"),
            similarity=i / 100,
        )
        for i in range(13)
    ]

    results = await recall_search("query")  # default limit == _MAX_RECALL_REFS

    assert len(results) == _MAX_RECALL_REFS == 10
    # Highest-similarity rows survive the cap (sorted desc).
    similarities = [r["similarity"] for r in results]
    assert similarities == sorted(similarities, reverse=True)
    assert min(similarities) == pytest.approx(0.03)  # s12..s3 survive, s0..s2 dropped


# --- dedupe_and_cap_recall_refs: isolated unit tests -------------------------


def test_dedupe_and_cap_keeps_highest_similarity_per_key():
    refs = [
        {"kind": "exchange", "session_id": "chat_session:s1", "similarity": 0.2},
        {"kind": "exchange", "session_id": "chat_session:s1", "similarity": 0.9},
    ]
    out = dedupe_and_cap_recall_refs(refs)
    assert len(out) == 1
    assert out[0]["similarity"] == 0.9


def test_dedupe_and_cap_never_dedupes_across_kinds():
    refs = [
        {"kind": "exchange", "session_id": "chat_session:s1", "similarity": 0.5},
        {"kind": "annotation", "annotation_id": "source_annotation:a1", "similarity": 0.5},
    ]
    out = dedupe_and_cap_recall_refs(refs)
    assert len(out) == 2


def test_dedupe_and_cap_respects_custom_limit():
    refs = [
        {"kind": "annotation", "annotation_id": f"source_annotation:a{i}", "similarity": i}
        for i in range(5)
    ]
    out = dedupe_and_cap_recall_refs(refs, limit=2)
    assert len(out) == 2
    assert [r["similarity"] for r in out] == [4, 3]


# --- get_exchange_content: dispatch on id prefix (mocked repo_query) --------


@pytest.mark.asyncio
async def test_get_exchange_content_chat_exchange(monkeypatch):
    async def fake_repo_query(query_str, variables=None):
        assert "session.title" in query_str
        return [
            {
                "question": "What is a monad?",
                "gist": "We discussed monads as a design pattern.",
                "session_id": RecordID("chat_session", "s1"),
                "title": "Functional Programming Chat",
            }
        ]

    monkeypatch.setattr(recall, "repo_query", fake_repo_query)

    content = await get_exchange_content("chat_exchange:e1")

    assert content == {
        "question": "What is a monad?",
        "gist": "We discussed monads as a design pattern.",
        "session_id": "chat_session:s1",
        "title": "Functional Programming Chat",
    }


@pytest.mark.asyncio
async def test_get_exchange_content_source_annotation(monkeypatch):
    async def fake_repo_query(query_str, variables=None):
        assert "quote" in query_str
        return [
            {
                "quote": "highlighted passage",
                "note": "important!",
                "tags": ["key-idea"],
                "page": 12,
                "source_id": RecordID("source", "src1"),
            }
        ]

    monkeypatch.setattr(recall, "repo_query", fake_repo_query)

    content = await get_exchange_content("source_annotation:a1")

    assert content == {
        "quote": "highlighted passage",
        "note": "important!",
        "tags": ["key-idea"],
        "page": 12,
        "source_id": "source:src1",
    }


@pytest.mark.asyncio
async def test_get_exchange_content_unsupported_prefix_raises():
    from open_notebook.exceptions import InvalidInputError

    with pytest.raises(InvalidInputError):
        await get_exchange_content("note:n1")


# --- search_past_discussions: STRUCTURAL spoiler guard ----------------------


@pytest.mark.asyncio
async def test_search_past_discussions_never_leaks_gist_or_note(monkeypatch):
    """The metadata-only tool must never surface gist/note/answer text — that
    is the entire structural spoiler guard (coordinator decision 5)."""

    async def fake_recall_search(query, limit=5, minimum_score=0.35):
        # Realistic recall_search() output: the 11 contract fields plus the
        # extra "id" key (chat_exchange:.../source_annotation:...) that only
        # exists so get_past_discussion has something to address — see
        # recall.py:_normalize_recall_row's docstring. Still no gist/note.
        return [
            {
                "id": "chat_exchange:e1",
                "kind": "exchange",
                "title": "Prior chat",
                "session_id": "chat_session:s1",
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

    monkeypatch.setattr(chat_tools, "recall_search", fake_recall_search)

    raw = await chat_tools.search_past_discussions.ainvoke({"query": "monads", "limit": 5})
    parsed = json.loads(raw)

    assert parsed["count"] == 1
    for ref in parsed["results"]:
        assert "gist" not in ref
        assert "note" not in ref
        # Every contract key present (extra "id" tolerated — B3 filters it).
        assert set(_RECALL_REF_FIELDS) <= set(ref.keys())


@pytest.mark.asyncio
async def test_get_past_discussion_is_the_only_full_content_path(monkeypatch):
    async def fake_get_exchange_content(ref_id):
        assert ref_id == "chat_exchange:e1"
        return {
            "question": "What is a monad?",
            "gist": "A monad is a monoid in the category of endofunctors.",
            "session_id": "chat_session:s1",
            "title": "FP chat",
        }

    monkeypatch.setattr(chat_tools, "get_exchange_content", fake_get_exchange_content)

    raw = await chat_tools.get_past_discussion.ainvoke({"ref_id": "chat_exchange:e1"})
    parsed = json.loads(raw)

    assert parsed["gist"] == "A monad is a monoid in the category of endofunctors."
