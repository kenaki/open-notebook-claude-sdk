"""Unit tests for the study-memory domain substrate (chunk A1).

Focuses on ChatExchange._prepare_save_data — the record-id coercion that turns
plain string links into SurrealDB RecordIDs for the SCHEMAFULL chat_exchange
table. Pure serialization logic, no database needed.
"""

from surrealdb import RecordID

from open_notebook.domain.notebook import ChatExchange


def _make_exchange(**overrides) -> ChatExchange:
    base = dict(
        session="chat_session:abc",
        scope="notebook",
        notebook="notebook:nb1",
        question="What is a monad?",
        message_id="ai-1234",
    )
    base.update(overrides)
    return ChatExchange(**base)


def test_session_coerced_to_record_id():
    data = _make_exchange()._prepare_save_data()
    assert isinstance(data["session"], RecordID)
    assert str(data["session"]) == "chat_session:abc"


def test_notebook_scope_coerces_notebook_only():
    data = _make_exchange(scope="notebook", notebook="notebook:nb1")._prepare_save_data()
    assert isinstance(data["notebook"], RecordID)
    assert str(data["notebook"]) == "notebook:nb1"
    # source is a nullable option<record<source>> field: kept as None (written
    # as NONE), never left as a bare string that SurrealDB would reject.
    assert data["source"] is None
    assert data["scope"] == "notebook"


def test_source_scope_coerces_source_link():
    data = _make_exchange(
        scope="source", notebook=None, source="source:s1"
    )._prepare_save_data()
    assert isinstance(data["source"], RecordID)
    assert str(data["source"]) == "source:s1"
    assert data["notebook"] is None


def test_annotation_ids_coerced_element_wise():
    data = _make_exchange(
        scope="source",
        notebook=None,
        source="source:s1",
        annotation_ids=["source_annotation:a1", "source_annotation:a2"],
    )._prepare_save_data()
    assert isinstance(data["annotation_ids"], list)
    assert all(isinstance(a, RecordID) for a in data["annotation_ids"])
    assert [str(a) for a in data["annotation_ids"]] == [
        "source_annotation:a1",
        "source_annotation:a2",
    ]


def test_empty_annotation_ids_stays_empty_list():
    data = _make_exchange()._prepare_save_data()
    # nullable/default empty list survives as [] (never coerced to a string).
    assert data.get("annotation_ids", []) == []
