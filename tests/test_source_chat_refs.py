"""Unit tests for the structured chat-reference helpers (Chunk D2).

Covers the pure resolution/injection primitives in
``open_notebook.graphs.source_chat`` on synthetic block/annotation data — no DB,
no LLM, no checkpoint:

- ``annotation_block_content``: per-type rendering of an anchored block.
- ``build_annotation_context_section``: the ``REFERENCED ANNOTATION n`` block.

The router->worker transport is now typed fields on ``ChatCompletionInput``
(``annotation_context`` + ``annotation_refs``) rather than a message-content
codec; ``test_chat_input_carries_annotation_fields`` pins that channel.
"""

from commands.chat_commands import ChatCompletionInput
from open_notebook.graphs.source_chat import (
    annotation_block_content,
    build_annotation_context_section,
)

from api.routers.source_chat import RecallRef, _parse_recall_refs

# --- annotation_block_content -------------------------------------------------


def test_block_content_text_block():
    block = {"type": "paragraph", "text": "The quick brown fox."}
    assert annotation_block_content(block, None) == "The quick brown fox."


def test_block_content_equation_uses_latex():
    block = {"type": "equation", "latex": "v = a t", "text": "ignored"}
    assert annotation_block_content(block, None) == "v = a t"


def test_block_content_equation_falls_back_to_text_then_quote():
    assert annotation_block_content({"type": "equation"}, "quoted") == "quoted"
    assert annotation_block_content({"type": "equation"}, None) == "(equation)"


def test_block_content_figure_with_caption():
    block = {"type": "figure", "text": "Diagram of the apparatus"}
    assert annotation_block_content(block, None) == "figure: Diagram of the apparatus"


def test_block_content_figure_without_caption():
    assert annotation_block_content({"type": "figure"}, None) == "figure: (image)"
    assert annotation_block_content({"type": "table"}, None) == "figure: (image)"


def test_block_content_text_falls_back_to_quote_then_placeholder():
    assert annotation_block_content({"type": "paragraph"}, "quoted text") == "quoted text"
    assert annotation_block_content({"type": "paragraph"}, None) == "(no text)"


# --- build_annotation_context_section -----------------------------------------


def test_section_empty_list_is_empty_string():
    assert build_annotation_context_section([]) == ""


def test_section_renders_crumb_content_and_note():
    resolved = [
        {
            "section_path": ["Chapter 2", "Kinematics"],
            "content": "v = a t",
            "note": "check derivation",
        },
        {"section_path": [], "content": "figure: apparatus", "note": None},
    ]
    out = build_annotation_context_section(resolved)
    assert "REFERENCED ANNOTATIONS" in out
    assert "REFERENCED ANNOTATION 1: [Chapter 2 > Kinematics] v = a t" in out
    assert "User note: check derivation" in out
    # Second ref: unsectioned crumb, no note line.
    assert "REFERENCED ANNOTATION 2: [unsectioned] figure: apparatus" in out
    assert out.count("User note:") == 1


def test_section_blank_content_gets_placeholder():
    out = build_annotation_context_section([{"section_path": [], "content": "  ", "note": None}])
    assert "[unsectioned] (no text)" in out


# --- router->worker transport (typed command fields) --------------------------


def test_chat_input_carries_annotation_fields():
    """The resolved context + refs ride as typed fields on the command input,
    NOT embedded in ``message`` (which stays the clean user prose)."""
    context = "REFERENCED ANNOTATION 1: [Intro] hello"
    refs = [{"id": "source_annotation:a", "quote": "hello", "block_seq": 5, "page": 2}]
    inp = ChatCompletionInput(
        session_id="chat_session:x",
        message="What does this mean?",
        kind="source",
        source_id="source:s",
        annotation_context=context,
        annotation_refs=refs,
    )
    assert inp.message == "What does this mean?"
    assert inp.annotation_context == context
    assert inp.annotation_refs == refs


def test_chat_input_annotation_fields_default_to_empty():
    """The no-refs path leaves the fields at their empty defaults so the source
    branch of chat_commands builds a clean human message with no extra kwargs."""
    inp = ChatCompletionInput(session_id="chat_session:x", message="hello")
    assert inp.annotation_context is None
    assert inp.annotation_refs == []


# --- recall_refs deserialization (study-memory Track B, chunk B3) -------------


_RAW_ANNOTATION_REF = {
    "id": "source_annotation:xyz",  # backend-only key — must be dropped
    "kind": "annotation",
    "title": "Chapter 2: Kinematics",
    "session_id": None,
    "scope": None,
    "source_id": "source:s1",
    "notebook_id": None,
    "message_id": None,
    "annotation_id": "source_annotation:xyz",
    "page": 12,
    "quote": "v = a t",
    "similarity": 0.91,
}


def test_parse_recall_refs_serializes_contract_shape():
    refs = _parse_recall_refs({"recall_refs": [_RAW_ANNOTATION_REF]})
    assert refs is not None
    assert len(refs) == 1
    ref = refs[0]
    assert isinstance(ref, RecallRef)
    assert ref.kind == "annotation"
    assert ref.title == "Chapter 2: Kinematics"
    assert ref.source_id == "source:s1"
    assert ref.annotation_id == "source_annotation:xyz"
    assert ref.page == 12
    assert ref.quote == "v = a t"
    assert ref.similarity == 0.91


def test_parse_recall_refs_drops_backend_only_id_key():
    """recall_search emits an extra backend-only `id` key (X-recall-id-key);
    the frontend contract is exactly 11 fields and must never see it."""
    refs = _parse_recall_refs({"recall_refs": [_RAW_ANNOTATION_REF]})
    ref = refs[0]
    assert not hasattr(ref, "id")
    assert "id" not in ref.model_dump()


def test_parse_recall_refs_absent_key_yields_none():
    """Older sessions / human turns with no recall_refs key must deserialize
    cleanly to None, never raise."""
    assert _parse_recall_refs({}) is None
    assert _parse_recall_refs({"thinking": "unrelated"}) is None


def test_parse_recall_refs_empty_list_yields_none():
    assert _parse_recall_refs({"recall_refs": []}) is None
