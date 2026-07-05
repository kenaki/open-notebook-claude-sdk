"""
Unit tests for to-fix/003 — `_sections_from_toc` content bounding.

Pure-function tests: a stub PyMuPDF ``doc`` (supports ``len(doc)`` and
``doc[p].get_text("text")``) plus synthetic Docling-style markdown. No DB,
no real PDF.
"""

from typing import List

from commands.section_commands import (
    _PAGE_BUDGET_FLOOR,
    _sections_from_markdown_headings,
    _sections_from_toc,
)


class StubPage:
    def __init__(self, text: str):
        self._text = text

    def get_text(self, kind: str) -> str:
        assert kind == "text"
        return self._text


class StubDoc:
    def __init__(self, page_texts: List[str]):
        self._pages = [StubPage(t) for t in page_texts]

    def __len__(self) -> int:
        return len(self._pages)

    def __getitem__(self, idx: int) -> StubPage:
        return self._pages[idx]


def _synthetic_book():
    """Seven-page book: 3 chapters each with an 'Exercises' subsection, one
    admonition pseudo-heading ('# Tip'), and a final TOC entry whose title
    matches no markdown heading (PyMuPDF fallback path)."""
    full_text = (
        "# Chapter 1\n"
        "chapter one intro text\n"
        "## Exercises\n"
        "exercises one body\n"
        "# Tip\n"
        "tip body attached to exercises one\n"
        "# Chapter 2\n"
        "chapter two intro text\n"
        "## Exercises\n"
        "exercises two body\n"
        "# Chapter 3\n"
        "chapter three intro text\n"
        "## Exercises\n"
        "exercises three body\n"
        "closing text without a heading\n"
    )
    page_texts = [
        "Chapter 1\nchapter one intro text",
        "Exercises\nexercises one body\nTip\ntip body attached to exercises one",
        "Chapter 2\nchapter two intro text",
        "Exercises\nexercises two body",
        "Chapter 3\nchapter three intro text",
        "Exercises\nexercises three body",
        "closing text without a heading RAW PAGE SEVEN",
    ]
    toc = [
        [1, "Chapter 1", 1],
        [2, "Exercises", 2],
        [1, "Chapter 2", 3],
        [2, "Exercises", 4],
        [1, "Chapter 3", 5],
        [2, "Exercises", 6],
        [1, "Missing Title", 7],
    ]
    return StubDoc(page_texts), toc, full_text, page_texts


def test_repeated_titles_get_distinct_char_starts():
    doc, toc, full_text, _ = _synthetic_book()
    sections = _sections_from_toc(doc, toc, full_text)

    assert len(sections) == len(toc)
    exercises = [s for s in sections if s["title"] == "Exercises"]
    assert len(exercises) == 3

    starts = [s["char_start"] for s in exercises]
    assert all(cs is not None for cs in starts)
    assert len(set(starts)) == 3, "repeated titles must map to distinct positions"
    assert starts == sorted(starts), "positions must advance in document order"

    # Each repeat slices ITS OWN region, not the first occurrence's
    assert "exercises one body" in exercises[0]["content"]
    assert "exercises two body" in exercises[1]["content"]
    assert "exercises three body" in exercises[2]["content"]
    assert "exercises two body" not in exercises[0]["content"]
    assert "exercises one body" not in exercises[1]["content"]


def test_admonition_headings_are_not_candidates_or_sections():
    doc, toc, full_text, _ = _synthetic_book()
    sections = _sections_from_toc(doc, toc, full_text)

    assert not any(s["title"].strip().lower() == "tip" for s in sections)
    # The '# Tip' callout stays inside the enclosing Exercises slice — it
    # neither bounds the slice nor terminates it early.
    exercises_one = sections[1]
    assert "tip body attached to exercises one" in exercises_one["content"]


def test_parent_aggregates_children_with_narrow_stored_page_range():
    doc, toc, full_text, _ = _synthetic_book()
    sections = _sections_from_toc(doc, toc, full_text)

    chapter_two = sections[2]
    # Stored page range stays narrow (ends before the first child page) …
    assert (chapter_two["page_start"], chapter_two["page_end"]) == (2, 2)
    # … while content still aggregates the whole chapter (existing semantics).
    assert "chapter two intro text" in chapter_two["content"]
    assert "exercises two body" in chapter_two["content"]
    assert "chapter three intro text" not in chapter_two["content"]


def test_unmatched_title_falls_back_to_page_text():
    doc, toc, full_text, page_texts = _synthetic_book()
    sections = _sections_from_toc(doc, toc, full_text)

    missing = sections[6]
    assert missing["title"] == "Missing Title"
    assert missing["char_start"] is None
    assert missing["content_from_pages"] is True
    assert missing["content"] == page_texts[6].strip()


def test_no_content_exceeds_page_budget():
    doc, toc, full_text, page_texts = _synthetic_book()
    sections = _sections_from_toc(doc, toc, full_text)

    # Everything in the synthetic book is tiny — well under the budget floor.
    for s in sections:
        assert len(s["content"]) <= _PAGE_BUDGET_FLOOR


def test_misbounded_slice_replaced_by_page_range_text():
    """A matched heading with no bounded end (next title unmatched) slices to
    EOF; the page budget must catch it and swap in the raw page text."""
    filler = ("lorem ipsum " * 10 + "\n") * 300  # ~36K chars, > budget floor
    full_text = "# Preface\n" + filler
    page_texts = ["Preface small raw text", "next chapter raw text"]
    toc = [
        [1, "Preface", 1],
        [1, "Unmatchable Next", 2],
    ]
    sections = _sections_from_toc(StubDoc(page_texts), toc, full_text)

    preface = sections[0]
    assert preface["char_start"] == 0
    assert preface["content_from_pages"] is True, "mis-bounded slice must fall back"
    assert preface["content"] == page_texts[0].strip()

    unmatched = sections[1]
    assert unmatched["content_from_pages"] is True
    assert unmatched["content"] == page_texts[1].strip()


def test_markdown_headings_path_filters_admonitions():
    full_text = (
        "# Alpha\n"
        "alpha body\n"
        "# Note\n"
        "note body inside alpha\n"
        "# Beta\n"
        "beta body\n"
    )
    sections = _sections_from_markdown_headings(full_text)

    assert [s["title"] for s in sections] == ["Alpha", "Beta"]
    assert "note body inside alpha" in sections[0]["content"]
    assert "beta body" not in sections[0]["content"]
