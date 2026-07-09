"""to-fix/006 — TOC-aligned reader outline (``open_notebook/parsers/outline.py``)."""

import pytest

from open_notebook.parsers.outline import (
    TocEntry,
    build_flat_outline,
    build_outline,
    headings_from_blocks,
    is_junk_heading,
    normalize_title,
    strip_numbering,
)


def h(seq: int, page: int, text: str, level: int = 1) -> dict:
    return {"seq": seq, "page": page, "text": text, "level": level}


def page_index(pages: dict[int, tuple[int, int]], page_count: int) -> list[list[int]]:
    """`{page: (lo, hi)}` -> the positional page_index finalize() writes."""
    return [list(pages.get(p, (0, -1))) for p in range(1, page_count + 1)]


# --- junk filter (option A) -------------------------------------------------


@pytest.mark.parametrize(
    "text", ["TIP", "Note", " warning ", "Caution", "IMPORTANT", "", "   "]
)
def test_admonitions_and_blanks_are_junk(text):
    assert is_junk_heading(text)


@pytest.mark.parametrize("text", ["OceanofPDF.com", "www.oceanofpdf.com", "z-lib.org"])
def test_watermarks_are_junk(text):
    assert is_junk_heading(text)


@pytest.mark.parametrize(
    "text", ["Let's walk through this code:", "In this equation:"]
)
def test_colon_terminated_lead_ins_are_junk(text):
    assert is_junk_heading(text)


@pytest.mark.parametrize(
    "text", ["CHAPTER 1", "Chapter 1.", "Part I", "Appendix A", "42", "7."]
)
def test_bare_enumerators_are_junk(text):
    """O'Reilly renders the chapter number as its own heading block."""
    assert is_junk_heading(text)


@pytest.mark.parametrize("text", ["CV", "CI", "Civil", "MIX", "Chapter 1. Basics"])
def test_roman_numeral_letters_do_not_make_a_heading_junk(text):
    """An unprefixed `[ivxlc]+` match would eat real headings."""
    assert not is_junk_heading(text)


@pytest.mark.parametrize(
    "text",
    [
        # Real O'Reilly front-matter heading — must survive despite looking generic.
        "Code Examples",
        # 10 words: length must never be the discriminator.
        "Chapter 1. Introduction to Building AI Applications with Foundation Models",
        "Conventions Used in This Book",
        "Exercises",
        # Substring of an admonition marker, but not one.
        "Notes on Notation",
        "Important Considerations",
    ],
)
def test_real_headings_survive_the_filter(text):
    assert not is_junk_heading(text)


def test_build_flat_outline_drops_junk_and_keeps_order():
    headings = [h(0, 1, "The Landscape"), h(5, 1, "TIP"), h(9, 2, "Training Models")]
    out = build_flat_outline(headings, last_seq=20)
    assert [e["title"] for e in out] == ["The Landscape", "Training Models"]
    # Same-level siblings: the first closes where the second begins.
    assert out[0]["subtree_end"] == 8
    assert out[1]["subtree_end"] == 20


def test_bare_enumerator_survives_only_when_the_toc_names_it():
    """The junk filter runs on non-TOC headings only. A book whose bookmark is
    literally "Chapter 1" keeps it; the same text as a stray block does not.
    On the no-TOC fallback path there is no bookmark to protect it."""
    headings = [h(0, 1, "Chapter 1"), h(4, 1, "Regularization")]
    page_idx = page_index({1: (0, 9)}, 1)

    with_toc = build_outline(headings, page_idx, [TocEntry(1, "Chapter 1", 1)], 9)
    assert [e["title"] for e in with_toc] == ["Chapter 1", "Regularization"]

    without_toc = build_outline(headings, page_idx, [], 9)
    assert [e["title"] for e in without_toc] == ["Regularization"]


# --- normalization ----------------------------------------------------------


def test_normalize_title_survives_punctuation_and_case():
    assert normalize_title("The Machine-Learning Landscape!") == (
        "the machine learning landscape"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1. The Machine Learning Landscape", "The Machine Learning Landscape"),
        ("Chapter 2. Understanding Foundation Models", "Understanding Foundation Models"),
        ("Part I. The Fundamentals", "The Fundamentals"),
        ("A. Machine Learning Project Checklist", "Machine Learning Project Checklist"),
        # No enumeration to strip.
        ("Exercises", "Exercises"),
        # A decimal that is part of the title, not a prefix enumerator.
        ("3.5 Tips", "3.5 Tips"),
    ],
)
def test_strip_numbering(raw, expected):
    assert strip_numbering(raw) == expected


# --- alignment --------------------------------------------------------------


def test_toc_supplies_hierarchy_that_flat_headings_lack():
    """The core defect: every heading block arrives at level 1."""
    headings = [h(0, 1, "Preface"), h(4, 2, "Objective"), h(8, 3, "Roadmap")]
    toc = [
        TocEntry(1, "Preface", 1),
        TocEntry(2, "Objective", 2),
        TocEntry(2, "Roadmap", 3),
    ]
    out = build_outline(headings, page_index({1: (0, 3), 2: (4, 7), 3: (8, 11)}, 3), toc, 11)

    assert [(e["seq"], e["level"], e["title"]) for e in out] == [
        (0, 1, "Preface"),
        (4, 2, "Objective"),
        (8, 2, "Roadmap"),
    ]
    # Preface's subtree spans both children; the last child runs to the end.
    assert out[0]["subtree_end"] == 11
    assert out[1]["subtree_end"] == 7


def test_repeated_titles_map_to_distinct_blocks():
    """"Exercises" appears 19× in one book; a naive title index collapses them."""
    headings = [
        h(0, 1, "Chapter 1"),
        h(3, 2, "Exercises"),
        h(6, 3, "Chapter 2"),
        h(9, 4, "Exercises"),
    ]
    toc = [
        TocEntry(1, "Chapter 1", 1),
        TocEntry(2, "Exercises", 2),
        TocEntry(1, "Chapter 2", 3),
        TocEntry(2, "Exercises", 4),
    ]
    out = build_outline(headings, page_index({1: (0, 2), 2: (3, 5), 3: (6, 8), 4: (9, 11)}, 4), toc, 11)
    assert [e["seq"] for e in out] == [0, 3, 6, 9]


def test_numbering_stripped_repair_matches_chapter_headings():
    """TOC carries `1. Title`; the rendered heading does not."""
    headings = [h(0, 1, "The Machine Learning Landscape"), h(5, 9, "Exercises")]
    toc = [
        TocEntry(1, "1. The Machine Learning Landscape", 1),
        TocEntry(2, "Exercises", 9),
    ]
    out = build_outline(headings, page_index({1: (0, 4), 9: (5, 9)}, 9), toc, 9)
    # Matched to the block (seq 0), but titled from the TOC.
    assert out[0]["seq"] == 0
    assert out[0]["title"] == "1. The Machine Learning Landscape"
    assert out[1]["seq"] == 5


def test_numbering_repair_cannot_reorder_earlier_matches():
    """Regression guard: a greedy cursor let a stripped match claim a later
    entry's block and drag the cursor past it (97.8% -> 94.5% on a real book).
    The repair pass is bounded by already-matched neighbours instead."""
    headings = [
        h(0, 1, "Introduction"),
        h(4, 5, "Understanding Foundation Models"),
        h(8, 9, "Evaluation"),
    ]
    toc = [
        TocEntry(1, "Chapter 1. Introduction", 1),
        TocEntry(1, "Chapter 2. Understanding Foundation Models", 5),
        TocEntry(1, "Chapter 3. Evaluation", 9),
    ]
    out = build_outline(headings, page_index({1: (0, 3), 5: (4, 7), 9: (8, 11)}, 9), toc, 11)
    assert [e["seq"] for e in out] == [0, 4, 8]


def test_unmatched_toc_entry_falls_back_to_its_page():
    """Front matter with no rendered heading still needs a jump target."""
    headings = [h(6, 3, "Preface")]
    toc = [TocEntry(1, "Cover", 1), TocEntry(1, "Preface", 3)]
    out = build_outline(headings, page_index({1: (0, 2), 3: (6, 9)}, 3), toc, 9)
    assert [(e["seq"], e["title"]) for e in out] == [(0, "Cover"), (6, "Preface")]


def test_unmatched_toc_entry_on_an_empty_page_is_dropped():
    """No blocks on the page => no seq => nothing to scroll to."""
    headings = [h(6, 3, "Preface")]
    toc = [TocEntry(1, "Cover", 1), TocEntry(1, "Preface", 3)]
    # Page 1 carries no blocks (inverted range).
    out = build_outline(headings, page_index({3: (6, 9)}, 3), toc, 9)
    assert [e["title"] for e in out] == ["Preface"]


def test_page_fallback_never_duplicates_a_matched_seq():
    """An unmatched entry landing on a page whose first block is another
    entry's heading must not emit two entries at the same seq."""
    headings = [h(0, 1, "Preface")]
    toc = [TocEntry(1, "Cover", 1), TocEntry(1, "Preface", 1)]
    out = build_outline(headings, page_index({1: (0, 5)}, 1), toc, 5)
    seqs = [e["seq"] for e in out]
    assert len(seqs) == len(set(seqs)) == 1


def test_non_toc_headings_are_kept_and_nested():
    """The TOC omits ~200 real sub-headings per book. They must survive, one
    level deeper than the TOC entry they sit under — and junk must not."""
    headings = [
        h(0, 1, "Chapter 1"),
        h(2, 1, "Language models"),  # real, absent from the TOC
        h(4, 1, "TIP"),  # junk
        h(6, 2, "Chapter 2"),
    ]
    toc = [TocEntry(1, "Chapter 1", 1), TocEntry(1, "Chapter 2", 2)]
    out = build_outline(headings, page_index({1: (0, 5), 2: (6, 9)}, 2), toc, 9)
    assert [(e["seq"], e["level"], e["title"]) for e in out] == [
        (0, 1, "Chapter 1"),
        (2, 2, "Language models"),
        (6, 1, "Chapter 2"),
    ]


def test_heading_before_the_first_toc_entry_stays_level_1():
    headings = [h(0, 1, "Cover Title"), h(4, 2, "Preface")]
    toc = [TocEntry(1, "Preface", 2)]
    out = build_outline(headings, page_index({1: (0, 3), 2: (4, 9)}, 2), toc, 9)
    assert [(e["seq"], e["level"]) for e in out] == [(0, 1), (4, 1)]


def test_page_window_rejects_a_far_away_title_collision():
    """A title repeated far from its bookmark page must not be matched to it."""
    headings = [h(0, 50, "Summary")]
    toc = [TocEntry(1, "Summary", 2)]
    out = build_outline(headings, page_index({2: (0, 0)}, 2), toc, 0)
    # Page-fallback (seq 0 is the only block), not a match on the far heading.
    assert out[0]["title"] == "Summary"
    # ...and the far heading is still carried as a non-TOC entry, deduped to one.
    assert len(out) == 1


def test_levels_are_capped():
    headings = [h(0, 1, "Deep")]
    toc = [TocEntry(99, "Deep", 1)]
    out = build_outline(headings, page_index({1: (0, 1)}, 1), toc, 1)
    assert out[0]["level"] == 6


def test_empty_toc_degrades_to_the_flat_filtered_outline():
    headings = [h(0, 1, "The Landscape"), h(3, 1, "NOTE")]
    out = build_outline(headings, page_index({1: (0, 5)}, 1), [], 5)
    assert [e["title"] for e in out] == ["The Landscape"]


# --- block projection -------------------------------------------------------


def test_headings_from_blocks_filters_by_type():
    blocks = [
        {"seq": 0, "page": 1, "type": "heading", "text": "H", "level": 1},
        {"seq": 1, "page": 1, "type": "paragraph", "text": "p", "level": None},
    ]
    assert headings_from_blocks(blocks) == [
        {"seq": 0, "page": 1, "text": "H", "level": 1}
    ]
