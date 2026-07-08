"""Unit tests for the structured chat-reference helpers (Chunk D2).

Covers the pure resolution/injection primitives in
``open_notebook.graphs.source_chat`` on synthetic block/annotation data — no DB,
no LLM, no checkpoint:

- ``annotation_block_content``: per-type rendering of an anchored block.
- ``build_annotation_context_section``: the ``REFERENCED ANNOTATION n`` block.
- ``encode_annotation_payload`` / ``extract_annotation_payload``: the
  sentinel-delimited router->worker codec (round trip + degrade paths).
"""

from open_notebook.graphs.source_chat import (
    ANNOTATION_CTX_SENTINEL,
    annotation_block_content,
    build_annotation_context_section,
    encode_annotation_payload,
    extract_annotation_payload,
)

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


# --- encode / extract round trip ----------------------------------------------


def test_encode_extract_round_trip():
    context = "REFERENCED ANNOTATION 1: [Intro] hello"
    refs = [{"id": "source_annotation:a", "quote": "hello", "block_seq": 5, "page": 2}]
    encoded = encode_annotation_payload(context, refs)
    assert encoded.startswith(ANNOTATION_CTX_SENTINEL)

    message = "What does this mean?" + encoded
    clean, out_ctx, out_refs = extract_annotation_payload(message)
    assert clean == "What does this mean?"
    assert out_ctx == context
    assert out_refs == refs


def test_encode_empty_returns_empty_string():
    assert encode_annotation_payload("", []) == ""


def test_extract_without_sentinel_is_unchanged():
    assert extract_annotation_payload("plain message") == ("plain message", "", None)


def test_extract_non_string_is_unchanged():
    payload = [{"type": "text", "text": "hi"}]
    assert extract_annotation_payload(payload) == (payload, "", None)


def test_extract_malformed_json_degrades_to_clean_head():
    message = "hi" + ANNOTATION_CTX_SENTINEL + "{not valid json"
    clean, ctx, refs = extract_annotation_payload(message)
    assert clean == "hi"
    assert ctx == ""
    assert refs is None
