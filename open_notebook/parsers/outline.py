"""Reader outline derivation (to-fix/006).

The outline shown by ``ReaderOutline`` is the parse header's ``section_index``.
Historically it was every block Docling classified as a heading, unfiltered and
with ``level`` always 1 — Docling's PDF pipeline calls ``add_heading()`` without
a level, so the layout path can never produce hierarchy. On a 1,126-page book
that yielded 882 flat entries, 235 of them callout boxes (``TIP``/``NOTE``),
watermark lines and sentence fragments the layout model mistook for headings.

This module derives the outline instead from the PDF's own TOC bookmarks — the
authoritative hierarchy — aligned back onto heading blocks so each entry keeps a
``seq`` to scroll to:

- :func:`build_outline` matches each TOC entry to a heading block by normalized
  title within a page window, walking a monotonic ``seq`` cursor so a repeated
  title ("Exercises" ×19) maps to distinct blocks instead of collapsing onto the
  first. Measured coverage: 93–98% on exact title match.
- Entries that still miss (front matter with no rendered heading, titles Docling
  dropped) fall back to the first block on their page, so every TOC entry keeps a
  jump target.
- Heading blocks absent from the TOC are **kept**, nested one level under their
  preceding TOC entry. They are not junk by virtue of being absent: the TOC omits
  ~200 real sub-headings per test book (``Masked language model``,
  ``Self-supervision``). They are junk-filtered instead, via :func:`is_junk_heading`.

Without a TOC (no bookmarks, or a non-PDF parser) :func:`build_outline` degrades
to :func:`build_flat_outline` — today's flat list, but junk-filtered.

:func:`read_pdf_toc` is the seam: bookmarks are the only TOC provider today. A
synthesized-TOC provider (parsing a printed contents page) can slot in behind it
without touching any caller. Pure and DB-free; ``fitz`` is imported lazily so the
matching logic stays unit-testable without a PDF.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence

from loguru import logger

# A heading may nest no deeper than markdown allows (and than the outline
# dropdown can indent).
MAX_LEVEL = 6

# A TOC entry's title must appear on a heading block within this many pages of
# the bookmark's target page. Bookmarks point at the page a section *starts* on;
# a heading can render a page early or late when a section break falls mid-page.
PAGE_WINDOW = 2

# to-fix/003 + /006: Docling emits O'Reilly's callout boxes as SectionHeaderItem,
# so `TIP` / `NOTE` / `WARNING` become heading blocks and land in the outline
# verbatim (179 of 882 entries on one book). They are never section titles.
ADMONITION_MARKERS = frozenset({"tip", "note", "warning", "caution", "important"})

# Ebook-conversion watermarks, rendered as standalone bold lines and classified
# as headings (20 entries on the same book).
_WATERMARK_RE = re.compile(r"^\s*(?:www\.)?(?:oceanofpdf|z-lib|libgen)\b", re.I)

# Leading enumeration a TOC carries but the rendered heading often does not:
# "1. Title", "Chapter 1. Title", "Part I. Title", "A. Appendix Title".
_NUMBERING_RE = re.compile(
    r"^\s*(?:chapter|part|appendix|section)?\s*"
    r"(?:\d{1,3}|[ivxlcIVXLC]{1,7}|[A-Z])[.:)]\s+",
    re.I,
)

# A heading that is *only* an enumerator ("CHAPTER 1", "Part I", a stray folio).
# O'Reilly renders the chapter number as its own block above the chapter title,
# so it becomes a heading with no title of its own. Never a TOC entry: those are
# matched by title and bypass the junk filter entirely.
#
# A bare roman numeral only counts when a keyword introduces it. Unprefixed,
# `[ivxlc]+` matches real headings — "CV", "CI", "civil" are all spelled from
# roman-numeral letters.
_BARE_ENUMERATOR_RE = re.compile(
    r"^\s*(?:(?:chapter|part|appendix|section)\s+(?:\d{1,4}|[ivxlc]{1,7}|[a-z])|\d{1,4})"
    r"\s*[.:)]?\s*$",
    re.I,
)


class TocEntry(NamedTuple):
    """One resolved TOC entry. ``page`` is 1-based **physical**, not printed."""

    level: int
    title: str
    page: int


def normalize_title(text: Optional[str]) -> str:
    """Casefold to alphanumeric words — survives dot leaders, punctuation and
    the ligature/whitespace drift between a bookmark title and its rendered
    heading."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def strip_numbering(text: Optional[str]) -> str:
    """Drop a leading ``1.`` / ``Chapter 2.`` / ``Part I.`` enumeration."""
    return _NUMBERING_RE.sub("", (text or "").strip())


def is_junk_heading(text: Optional[str]) -> bool:
    """True for a heading block that is not a section title.

    Deliberately conservative — it runs unprotected on the no-TOC fallback path,
    where a false positive silently deletes a real section from the outline. In
    particular it does **not** key on title length: ``Chapter 1. Introduction to
    Building AI Applications with Foundation Models`` is a genuine TOC entry at
    10 words, and ``Code Examples`` is a genuine O'Reilly front-matter heading
    despite looking like boilerplate.
    """
    stripped = (text or "").strip()
    if not stripped:
        return True
    if normalize_title(stripped) in ADMONITION_MARKERS:
        return True
    if _WATERMARK_RE.match(stripped):
        return True
    if _BARE_ENUMERATOR_RE.match(stripped):
        return True
    # A heading never ends in a colon; a lead-in sentence the layout model
    # mistook for one does ("Let's walk through this code:", "In this equation:").
    if stripped.endswith(":"):
        return True
    return False


def resolve_toc(doc: Any) -> List[TocEntry]:
    """Read a TOC off an already-open PyMuPDF document.

    The provider seam. Today: the PDF's embedded bookmarks. Entries with no
    usable page or an empty title are dropped rather than carried as holes.
    """
    try:
        raw = doc.get_toc() or []
    except Exception as exc:  # a malformed outline tree must not fail the parse
        logger.warning(f"resolve_toc: could not read bookmarks: {exc}")
        return []

    entries: List[TocEntry] = []
    for row in raw:
        try:
            level, title, page = int(row[0]), str(row[1]).strip(), int(row[2])
        except (ValueError, TypeError, IndexError):
            continue
        if page < 1 or not title:
            continue
        entries.append(TocEntry(max(1, level), title, page))
    return entries


def read_pdf_toc(pdf_path: Path) -> List[TocEntry]:
    """Open ``pdf_path`` and resolve its TOC. Returns ``[]`` on any failure —
    the caller degrades to a flat outline, never fails the parse."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("read_pdf_toc: PyMuPDF unavailable — outline stays flat")
        return []

    doc = None
    try:
        doc = fitz.open(str(pdf_path))
        return resolve_toc(doc)
    except Exception as exc:
        logger.warning(f"read_pdf_toc: could not open {pdf_path}: {exc}")
        return []
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def _first_seq_on_page(page_index: Sequence[Sequence[int]], page: int) -> Optional[int]:
    """Lowest block ``seq`` on a 1-based page, or None if the page holds none.

    ``page_index`` is positionally aligned (``index == page - 1``) and stores an
    inverted ``[0, -1]`` range for empty pages (see ``parsers/base.finalize``).
    """
    idx = page - 1
    if not (0 <= idx < len(page_index)):
        return None
    lo, hi = page_index[idx][0], page_index[idx][1]
    return lo if lo <= hi else None


def _assign_subtree_end(entries: List[Dict], last_seq: int) -> List[Dict]:
    """Fill ``subtree_end`` on a seq-ordered outline via a heading-level stack:
    an entry at level L closes every open entry with level >= L. Mutates and
    returns ``entries``."""
    stack: List[int] = []  # indices into `entries`
    for i, entry in enumerate(entries):
        while stack and entries[stack[-1]]["level"] >= entry["level"]:
            entries[stack.pop()]["subtree_end"] = entry["seq"] - 1
        stack.append(i)
    while stack:
        entries[stack.pop()]["subtree_end"] = last_seq
    return entries


def build_flat_outline(headings: Sequence[Dict], last_seq: int) -> List[Dict]:
    """Junk-filtered outline straight off the heading blocks (to-fix/006 option A).

    The no-TOC path. Hierarchy is whatever the parser supplied — for Docling's PDF
    pipeline that is uniformly level 1, which is exactly the flatness this module
    exists to route around when a TOC *is* available.
    """
    entries = [
        {
            "seq": h["seq"],
            "level": min(max(int(h.get("level") or 1), 1), MAX_LEVEL),
            "title": (h.get("text") or "").strip(),
            "subtree_end": None,
        }
        for h in headings
        if not is_junk_heading(h.get("text"))
    ]
    entries.sort(key=lambda e: e["seq"])
    return _assign_subtree_end(entries, last_seq)


def _match_toc_to_headings(
    toc: Sequence[TocEntry],
    headings: Sequence[Dict],
    page_window: int,
) -> List[Optional[int]]:
    """Index into ``headings`` for each TOC entry (None where unmatched).

    Two passes, both order-preserving:

    1. **Exact** normalized-title match, walking a monotonic cursor over heading
       indices so repeated titles map to successive blocks.
    2. **Numbering-stripped** match for whatever pass 1 missed, bounded to the
       gap between that entry's already-matched neighbours.

    Pass 2 is interval-bounded rather than cursor-driven on purpose. Stripping
    ``Chapter 2.`` widens the match set, and a greedy cursor then lets an early
    entry claim a block belonging to a later one and drag the cursor past it —
    measured as a *regression* from 97.8% to 94.5% coverage on one book. Bounding
    each repair to ``(prev_matched, next_matched)`` cannot reorder anything.
    """
    exact: Dict[str, List[int]] = defaultdict(list)
    loose: Dict[str, List[int]] = defaultdict(list)
    for i, h in enumerate(headings):
        text = h.get("text") or ""
        exact[normalize_title(text)].append(i)
        loose[normalize_title(strip_numbering(text))].append(i)

    picked: List[Optional[int]] = [None] * len(toc)
    used: set[int] = set()

    def _near(i: int, page: int) -> bool:
        return abs(int(headings[i]["page"]) - page) <= page_window

    cursor = -1
    for e, entry in enumerate(toc):
        for i in exact.get(normalize_title(entry.title), []):
            if i > cursor and i not in used and _near(i, entry.page):
                picked[e], cursor = i, i
                used.add(i)
                break

    for e, entry in enumerate(toc):
        if picked[e] is not None:
            continue
        lo = max((picked[j] for j in range(e) if picked[j] is not None), default=-1)
        hi = min(
            (picked[j] for j in range(e + 1, len(toc)) if picked[j] is not None),
            default=len(headings),
        )
        for i in loose.get(normalize_title(strip_numbering(entry.title)), []):
            if lo < i < hi and i not in used and _near(i, entry.page):
                picked[e] = i
                used.add(i)
                break

    return picked


def build_outline(
    headings: Sequence[Dict],
    page_index: Sequence[Sequence[int]],
    toc: Sequence[TocEntry],
    last_seq: int,
    page_window: int = PAGE_WINDOW,
) -> List[Dict]:
    """Hierarchical ``section_index`` from a TOC aligned onto heading blocks.

    ``headings`` are the heading blocks in ``seq`` order, each a dict with
    ``seq``, ``page`` (1-based) and ``text``. Returns entries
    ``{seq, level, title, subtree_end}`` in ``seq`` order, one per TOC entry plus
    every non-junk heading block the TOC omitted, nested beneath it.

    Falls back to :func:`build_flat_outline` when ``toc`` is empty.
    """
    if not toc:
        return build_flat_outline(headings, last_seq)

    picked = _match_toc_to_headings(toc, headings, page_window)
    matched = {i for i in picked if i is not None}

    entries: List[Dict] = []
    for e, entry in enumerate(toc):
        i = picked[e]
        if i is not None:
            seq = headings[i]["seq"]
        else:
            # No rendered heading (front matter, or Docling dropped it). Land on
            # the top of the bookmark's page rather than dropping the entry.
            seq = _first_seq_on_page(page_index, entry.page)
            if seq is None:
                continue
        entries.append(
            {
                "seq": seq,
                "level": min(entry.level, MAX_LEVEL),
                "title": entry.title,
                "subtree_end": None,
                "_toc": True,
            }
        )

    # Non-TOC headings nest one level under the nearest preceding TOC entry.
    toc_seqs = [e["seq"] for e in entries]
    toc_levels = [e["level"] for e in entries]
    for i, h in enumerate(headings):
        if i in matched or is_junk_heading(h.get("text")):
            continue
        at = bisect_right(toc_seqs, h["seq"]) - 1
        level = (toc_levels[at] + 1) if at >= 0 else 1
        entries.append(
            {
                "seq": h["seq"],
                "level": min(level, MAX_LEVEL),
                "title": (h.get("text") or "").strip(),
                "subtree_end": None,
                "_toc": False,
            }
        )

    # A page-fallback entry can land on a seq a real heading already owns.
    # Sort TOC entries first within a seq so the bookmark title wins the dedupe.
    entries.sort(key=lambda e: (e["seq"], not e["_toc"]))
    deduped: List[Dict] = []
    for entry in entries:
        if deduped and deduped[-1]["seq"] == entry["seq"]:
            continue
        deduped.append(entry)

    for entry in deduped:
        entry.pop("_toc", None)

    matched_count = len(matched)
    logger.info(
        f"build_outline: {matched_count}/{len(toc)} TOC entries matched to a "
        f"heading block ({matched_count / len(toc):.1%}); "
        f"{len(deduped)} outline entries from {len(headings)} heading blocks"
    )
    return _assign_subtree_end(deduped, last_seq)


def headings_from_blocks(blocks: Sequence[Any]) -> List[Dict]:
    """Project heading blocks (ParsedBlock, DocumentBlock or dict) to the
    ``{seq, page, text}`` dicts :func:`build_outline` consumes."""

    def field(block: Any, name: str) -> Any:
        return block.get(name) if isinstance(block, dict) else getattr(block, name, None)

    out: List[Dict] = []
    for block in blocks:
        btype = field(block, "type")
        if str(getattr(btype, "value", btype)) != "heading":
            continue
        out.append(
            {
                "seq": field(block, "seq"),
                "page": field(block, "page"),
                "text": field(block, "text"),
                "level": field(block, "level"),
            }
        )
    return out
