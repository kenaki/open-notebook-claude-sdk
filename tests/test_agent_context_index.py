"""Unit tests for the Claude-agent slim-context index (AGENT-CTX N1).

These cover the pure index builders (no DB / no SDK subprocess) plus the
degrade-never-fail payload slimmers in ``open_notebook.graphs.chat`` and
``open_notebook.graphs.source_chat``:

- ``build_agent_context_index``: sources/notes -> compact id+title index
- ``format_index_line``: per-record line formatting (dict or model records)
- ``build_source_agent_context``: single-source slim context for source chat
- ``_slim_agent_payload`` / ``_slim_source_agent_payload``: swap the rendered
  context blob for the slim index; on ANY error the original payload must be
  returned untouched (the E2BIG stdin guard stays the safety net).
"""

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

import open_notebook.graphs.chat as chat_graph
import open_notebook.graphs.source_chat as source_chat_graph
from open_notebook.domain.notebook import Note, Source
from open_notebook.graphs.chat import build_agent_context_index, format_index_line
from open_notebook.graphs.source_chat import build_source_agent_context


# --- format_index_line --------------------------------------------------------


def test_line_from_dict_record():
    line = format_index_line({"id": "source:abc", "title": "Greek History"}, "source")
    assert line == '- source:abc — "Greek History"'


def test_line_from_domain_models():
    source = Source(id="source:abc", title="Greek History")
    note = Note(id="note:xyz", title="My Note", content="body")
    assert format_index_line(source, "source") == '- source:abc — "Greek History"'
    assert format_index_line(note, "note") == '- note:xyz — "My Note"'


def test_line_prefixes_bare_id_exactly_once():
    assert format_index_line({"id": "abc", "title": "T"}, "source").startswith(
        "- source:abc "
    )
    # An already-prefixed id is not double-prefixed.
    assert format_index_line({"id": "source:abc", "title": "T"}, "source").startswith(
        "- source:abc "
    )


def test_line_missing_title_uses_untitled():
    line = format_index_line({"id": "source:abc"}, "source")
    assert line == '- source:abc — "Untitled"'


def test_line_without_id_is_none():
    assert format_index_line({"title": "No id"}, "source") is None
    assert format_index_line({}, "note") is None


def test_line_appends_abstract_when_present():
    line = format_index_line(
        {"id": "source:abc", "title": "T", "abstract": "A short abstract."}, "source"
    )
    assert line == '- source:abc — "T" — A short abstract.'


def test_line_ignores_empty_or_non_string_abstract():
    assert (
        format_index_line({"id": "source:a", "title": "T", "abstract": "   "}, "source")
        == '- source:a — "T"'
    )
    assert (
        format_index_line(
            {"id": "source:a", "title": "T", "abstract": ["not", "a", "string"]},
            "source",
        )
        == '- source:a — "T"'
    )


def test_line_abstract_whitespace_collapsed_and_truncated():
    messy = "First   line\nsecond\t line " + "x" * 400
    line = format_index_line(
        {"id": "source:a", "title": "T", "abstract": messy}, "source"
    )
    assert "\n" not in line and "\t" not in line
    assert "First line second line" in line
    assert line.endswith("…")
    # id + title + capped abstract stays compact
    assert len(line) < 400


def test_line_abstract_field_precedence():
    line = format_index_line(
        {
            "id": "source:a",
            "title": "T",
            "abstract": "the abstract",
            "summary": "the summary",
            "description": "the description",
        },
        "source",
    )
    assert line.endswith("— the abstract")
    line = format_index_line(
        {"id": "source:a", "title": "T", "summary": "the summary"}, "source"
    )
    assert line.endswith("— the summary")


# --- build_agent_context_index -------------------------------------------------


def test_index_lists_sources_then_notes():
    sources = [
        {"id": "source:abc", "title": "Greek History"},
        {"id": "source:def", "title": "Rome", "abstract": "A survey of Rome."},
    ]
    notes = [{"id": "note:xyz", "title": "My Note"}]
    text = build_agent_context_index(sources, notes)
    assert text == (
        chat_graph._AGENT_INDEX_HEADER
        + "\n\n"
        + '- source:abc — "Greek History"\n'
        + '- source:def — "Rome" — A survey of Rome.\n'
        + '- note:xyz — "My Note"'
    )


def test_index_header_names_the_mcp_tools():
    text = build_agent_context_index([], [])
    assert "mcp__open_notebook__" in text
    for tool in ("search", "get_source_outline", "get_section", "get_source", "get_note"):
        assert tool in text


def test_index_empty_lists():
    text = build_agent_context_index([], [])
    assert text.startswith(chat_graph._AGENT_INDEX_HEADER)
    assert "(This notebook has no sources or notes yet.)" in text
    # None behaves like empty
    assert build_agent_context_index(None, None) == text


def test_index_skips_records_without_id():
    text = build_agent_context_index(
        [{"title": "no id"}], [{"id": "note:ok", "title": "kept"}]
    )
    assert "no id" not in text
    assert '- note:ok — "kept"' in text


# --- build_source_agent_context (source chat) ----------------------------------


def test_source_context_line_and_hint():
    text = build_source_agent_context({"id": "source:abc", "title": "Greek History"})
    assert '- source:abc — "Greek History"' in text
    assert "full content is NOT inlined" in text
    assert "mcp__open_notebook__get_source_outline" in text
    assert "mcp__open_notebook__get_section" in text


def test_source_context_requires_id():
    with pytest.raises(ValueError):
        build_source_agent_context({"title": "No id"})


# --- _slim_agent_payload (chat) -------------------------------------------------


class _FakeNotebook:
    """Stand-in for a Notebook record (template reads name/description)."""

    def __init__(self, sources=None, notes=None, fail=False):
        self.name = "Test Notebook"
        self.description = "A test notebook"
        self._sources = sources or []
        self._notes = notes or []
        self._fail = fail

    async def get_sources(self, include_full_text: bool = False):
        if self._fail:
            raise RuntimeError("db down")
        return self._sources

    async def get_notes(self, include_content: bool = False):
        return self._notes


def _chat_payload(blob="OLD-BLOB " * 500):
    return [SystemMessage(content=blob), HumanMessage(content="hi")]


@pytest.mark.asyncio
async def test_slim_payload_replaces_blob_with_index():
    notebook = _FakeNotebook(
        sources=[{"id": "source:abc", "title": "Greek History"}],
        notes=[{"id": "note:xyz", "title": "My Note"}],
    )
    payload = _chat_payload()
    state = {"notebook": notebook, "context": "OLD-BLOB", "messages": []}

    result = await chat_graph._slim_agent_payload(payload, state)

    assert isinstance(result[0], SystemMessage)
    content = str(result[0].content)
    assert "OLD-BLOB" not in content
    assert "Notebook source index" in content
    assert '- source:abc — "Greek History"' in content
    assert '- note:xyz — "My Note"' in content
    # Template framing survives the re-render: notebook header + citation rules.
    assert "Test Notebook" in content
    assert "CITING INSTRUCTIONS" in content
    # Conversation messages ride along untouched.
    assert result[1] is payload[1]


@pytest.mark.asyncio
async def test_slim_payload_degrades_on_builder_error():
    payload = _chat_payload()
    state = {"notebook": _FakeNotebook(fail=True), "context": "OLD-BLOB"}

    result = await chat_graph._slim_agent_payload(payload, state)

    assert result is payload  # original payload object, untouched


@pytest.mark.asyncio
async def test_slim_payload_no_notebook_keeps_payload():
    payload = _chat_payload()
    assert await chat_graph._slim_agent_payload(payload, {"notebook": None}) is payload
    assert await chat_graph._slim_agent_payload(payload, None) is payload


@pytest.mark.asyncio
async def test_slim_payload_requires_leading_system_message():
    payload = [HumanMessage(content="hi")]
    state = {"notebook": _FakeNotebook()}
    assert await chat_graph._slim_agent_payload(payload, state) is payload
    assert await chat_graph._slim_agent_payload([], state) == []


# --- _slim_source_agent_payload (source chat) -----------------------------------


def _source_prompt_data(source=None):
    return {
        "source": source,
        "insights": [],
        "context": "OLD-SOURCE-BLOB",
        "context_indicators": {"sources": [], "insights": [], "notes": []},
    }


def test_slim_source_payload_replaces_blob():
    payload = [
        SystemMessage(content="OLD-SOURCE-BLOB " * 500),
        HumanMessage(content="hi"),
    ]
    prompt_data = _source_prompt_data(
        {"id": "source:abc", "title": "Greek History", "topics": []}
    )

    result = source_chat_graph._slim_source_agent_payload(payload, prompt_data)

    content = str(result[0].content)
    assert "OLD-SOURCE-BLOB" not in content
    assert '- source:abc — "Greek History"' in content
    assert "mcp__open_notebook__get_source_outline" in content
    # Template framing survives: the source header block is still rendered.
    assert "Greek History" in content
    assert result[1] is payload[1]


def test_slim_source_payload_degrades_when_source_has_no_id():
    payload = [SystemMessage(content="OLD-SOURCE-BLOB"), HumanMessage(content="hi")]
    prompt_data = _source_prompt_data({"title": "No id"})

    result = source_chat_graph._slim_source_agent_payload(payload, prompt_data)

    assert result is payload


def test_slim_source_payload_no_prompt_data_keeps_payload():
    payload = [SystemMessage(content="OLD-SOURCE-BLOB")]
    assert source_chat_graph._slim_source_agent_payload(payload, None) is payload
    assert (
        source_chat_graph._slim_source_agent_payload(payload, _source_prompt_data())
        is payload
    )
