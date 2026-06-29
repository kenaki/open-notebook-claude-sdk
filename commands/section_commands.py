"""
Section / chaptering commands for Open Notebook.

A3: Builds source_section tree from PDF TOC or markdown heading analysis.
    Two commands:
      - build_sections  : per-source chaptering (fire-and-forget from ingest graph)
      - backfill_sections: orchestrator that fans out build_sections for existing PDFs
"""
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command, submit_command

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Source, SourceSection
from open_notebook.exceptions import ConfigurationError


# ---------------------------------------------------------------------------
# Pydantic I/O models
# ---------------------------------------------------------------------------


class BuildSectionsInput(CommandInput):
    source_id: str


class BuildSectionsOutput(CommandOutput):
    success: bool
    source_id: str
    sections_created: int = 0
    processing_time: float
    error_message: Optional[str] = None


class BackfillSectionsInput(CommandInput):
    """No required inputs — fans out build_sections for all qualifying sources."""


class BackfillSectionsOutput(CommandOutput):
    success: bool
    sources_found: int = 0
    jobs_submitted: int = 0
    processing_time: float
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers — boundary detection
# ---------------------------------------------------------------------------


def _detect_page_offset(doc) -> Optional[int]:
    """
    Return the physical 0-based page index at which arabic numbered 'page 1' starts.
    Returns None if undetermined (identity mapping: physical 0 = printed 1).

    Reads PyMuPDF doc.get_page_labels() which returns dicts like:
      {'startpage': 8, 'prefix': '', 'style': 'D', 'firstpagenum': 1}
    """
    try:
        labels = doc.get_page_labels()
        if not labels:
            return None
        for spec in labels:
            # style 'D' or 'd' = decimal arabic numerals
            if spec.get("style") in ("D", "d") and spec.get("firstpagenum", 1) == 1:
                offset = spec.get("startpage", 0)
                logger.debug(f"page_offset detected: {offset}")
                return offset
        return None
    except Exception as exc:
        logger.debug(f"page_labels detection failed: {exc}")
        return None


def _sections_from_toc(doc, toc: List, full_text: str) -> List[Dict]:
    """
    Build sections using PDF TOC for page ranges, markdown headings for content.

    Strategy:
    - For each TOC entry, try to find the matching '#' heading in full_text (Docling markdown).
    - If found: content = markdown slice from that heading to the next same-or-higher heading.
    - If not found: fall back to raw PyMuPDF text extraction for that page range.
    """
    import re

    heading_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    heading_matches = list(heading_re.finditer(full_text))

    # Build case-insensitive title → char_start map (first occurrence wins)
    title_to_char: Dict[str, int] = {}
    for m in heading_matches:
        key = m.group(2).strip().lower()
        if key not in title_to_char:
            title_to_char[key] = m.start()

    n_pages = len(doc)
    sections = []

    for i, (level, title, page_1based) in enumerate(toc):
        page_start = max(0, page_1based - 1)  # 1-based → 0-based
        if i + 1 < len(toc):
            # End just before the next chapter's first page
            page_end = max(page_start, toc[i + 1][2] - 2)
        else:
            page_end = n_pages - 1
        page_end = min(page_end, n_pages - 1)

        # Try markdown heading slice for content
        char_start = title_to_char.get(title.strip().lower())
        if char_start is not None:
            # Find char_end = start of next entry at same or higher level
            char_end = len(full_text)
            for j in range(i + 1, len(toc)):
                lv2, t2, _ = toc[j]
                if lv2 <= level:
                    c = title_to_char.get(t2.strip().lower())
                    if c is not None and c > char_start:
                        char_end = c
                        break
            content = full_text[char_start:char_end].strip()
        else:
            # Fallback: raw text from PyMuPDF pages
            content_parts = []
            for p in range(page_start, page_end + 1):
                content_parts.append(doc[p].get_text("text"))
            content = "\n".join(content_parts).strip()

        sections.append(
            {
                "level": level,
                "title": title,
                "content": content,
                "page_start": page_start,
                "page_end": page_end,
            }
        )

    return sections


def _sections_from_markdown_headings(full_text: str) -> List[Dict]:
    """
    Parse markdown headings (# … ######) from full_text.

    Returns a flat list of section dicts with:
      level, title, content (markdown slice), char_start, char_end.
    Returns [] if no headings found.
    """
    import re

    heading_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(full_text))
    if not matches:
        return []

    sections = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        char_start = m.start()
        char_end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        content = full_text[char_start:char_end].strip()
        sections.append(
            {
                "level": level,
                "title": title,
                "content": content,
                "char_start": char_start,
                "char_end": char_end,
            }
        )
    return sections


def _enhance_with_page_numbers(doc, sections_data: List[Dict]) -> None:
    """
    For heading-based sections (no page_start yet), search each heading title
    in the PDF pages to estimate page_start. Then infer page_end from neighbors.
    """
    n_pages = len(doc)

    for sec in sections_data:
        title = sec.get("title", "")
        if not title or "page_start" in sec:
            continue
        title_lower = title.lower()
        for page_idx in range(n_pages):
            if title_lower in doc[page_idx].get_text("text").lower():
                sec["page_start"] = page_idx
                break

    # Infer page_end from next sibling's page_start
    for i in range(len(sections_data) - 1):
        cur_ps = sections_data[i].get("page_start")
        nxt_ps = sections_data[i + 1].get("page_start")
        if cur_ps is not None and nxt_ps is not None:
            sections_data[i]["page_end"] = max(cur_ps, nxt_ps - 1)

    if sections_data:
        sections_data[-1].setdefault("page_end", n_pages - 1)


def _build_tree_structure(sections_data: List[Dict]) -> None:
    """
    Assign parent_idx (index into sections_data) and sibling order in-place.

    Uses a level-aware stack: when a heading of level N is encountered, all
    stack entries with level >= N are popped before pushing the new entry.
    """
    stack: List[Tuple[int, int]] = []  # (level, idx)
    sibling_counter: Dict[Optional[int], int] = {}

    for i, sec in enumerate(sections_data):
        level = sec.get("level", 1)
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_idx: Optional[int] = stack[-1][1] if stack else None
        sec["parent_idx"] = parent_idx

        if parent_idx not in sibling_counter:
            sibling_counter[parent_idx] = 0
        sec["order"] = sibling_counter[parent_idx]
        sibling_counter[parent_idx] += 1

        stack.append((level, i))


# ---------------------------------------------------------------------------
# Core chaptering logic
# ---------------------------------------------------------------------------


async def _build_sections_for_source(source: Source) -> int:
    """
    Run the full chaptering pipeline for a single source.

    1. Delete existing source_section rows (idempotency).
    2. Try to open PDF via PyMuPDF for TOC + page-label detection.
    3. Detect boundaries (TOC → heading → single-section fallback).
    4. Build parent-child tree structure.
    5. Save SourceSection records (two passes: create, then wire parents).

    Returns number of sections created.
    """
    if not source.full_text:
        logger.info(f"Source {source.id} has no full_text — skipping section build")
        return 0

    full_text: str = source.full_text
    source_rid = ensure_record_id(str(source.id))

    # Delete existing sections (idempotency)
    await repo_query(
        "DELETE source_section WHERE source = $sid",
        {"sid": source_rid},
    )

    doc = None
    toc: List = []

    # Try to open the PDF for enhanced detection
    if source.asset and source.asset.file_path:
        fp = source.asset.file_path
        if Path(fp).exists() and fp.lower().endswith(".pdf"):
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(fp)
                toc = doc.get_toc()
                logger.debug(f"PDF opened: {len(doc)} pages, {len(toc)} TOC entries")

                # Detect and persist page_offset
                page_offset = _detect_page_offset(doc)
                if page_offset != source.page_offset:
                    source.page_offset = page_offset
                    await source.save()

            except Exception as exc:
                logger.warning(f"Could not open PDF {fp} with PyMuPDF: {exc}")
                doc = None
                toc = []

    # --- Boundary detection ---
    if toc:
        logger.info(f"Source {source.id}: using TOC ({len(toc)} entries)")
        sections_data = _sections_from_toc(doc, toc, full_text)
    else:
        sections_data = _sections_from_markdown_headings(full_text)
        if sections_data:
            logger.info(
                f"Source {source.id}: using markdown headings ({len(sections_data)} found)"
            )
            if doc:
                _enhance_with_page_numbers(doc, sections_data)
        else:
            logger.info(f"Source {source.id}: no headings — single-section fallback")
            sections_data = [
                {
                    "level": 1,
                    "title": source.title or "Full Document",
                    "content": full_text,
                    "page_start": 0,
                    "page_end": len(doc) - 1 if doc else None,
                }
            ]

    if doc:
        doc.close()

    # Build tree (parent_idx, order)
    _build_tree_structure(sections_data)

    # --- Two-pass DB save ---
    # Pass 1: create all sections without parent (order matters for sibling numbering)
    saved: List[SourceSection] = []
    for s in sections_data:
        section = SourceSection(
            source=str(source_rid),
            order=s.get("order", 0),
            level=s.get("level", 1),
            title=s.get("title", ""),
            content=s.get("content", ""),
            page_start=s.get("page_start"),
            page_end=s.get("page_end"),
            token_count=len(s.get("content", "").split()),
        )
        await section.save()
        s["_section_id"] = section.id
        saved.append(section)

    # Pass 2: wire parent references
    for i, (s, section) in enumerate(zip(sections_data, saved)):
        parent_idx = s.get("parent_idx")
        if parent_idx is not None:
            parent_raw_id = sections_data[parent_idx].get("_section_id")
            if parent_raw_id:
                section.parent = str(ensure_record_id(str(parent_raw_id)))
                await section.save()

    return len(saved)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@command(
    "build_sections",
    app="open_notebook",
    retry={
        "max_attempts": 3,
        "wait_strategy": "exponential_jitter",
        "wait_min": 2,
        "wait_max": 30,
        "stop_on": [ValueError, ConfigurationError],
        "retry_log_level": "debug",
    },
)
async def build_sections_command(input_data: BuildSectionsInput) -> BuildSectionsOutput:
    """
    Build the section tree for a single source document.

    Detection priority:
    1. PDF bookmarks (doc.get_toc()) — page-precise chapter boundaries.
    2. Markdown headings in full_text — heading-level nesting, optional page search.
    3. Single section spanning the whole document (fallback / headingless PDFs).

    Idempotent: deletes existing source_section rows before rebuilding.
    """
    start_time = time.time()

    try:
        logger.info(f"build_sections started for source: {input_data.source_id}")

        source = await Source.get(input_data.source_id)
        if not source:
            raise ValueError(f"Source '{input_data.source_id}' not found")

        sections_created = await _build_sections_for_source(source)

        processing_time = time.time() - start_time
        logger.info(
            f"build_sections: {sections_created} sections for {input_data.source_id} "
            f"in {processing_time:.2f}s"
        )
        return BuildSectionsOutput(
            success=True,
            source_id=input_data.source_id,
            sections_created=sections_created,
            processing_time=processing_time,
        )

    except ValueError as exc:
        processing_time = time.time() - start_time
        logger.error(f"build_sections permanent failure for {input_data.source_id}: {exc}")
        return BuildSectionsOutput(
            success=False,
            source_id=input_data.source_id,
            processing_time=processing_time,
            error_message=str(exc),
        )
    except Exception:
        # Transient — will retry
        raise


@command(
    "backfill_sections",
    app="open_notebook",
    retry={
        "max_attempts": 1,
        "stop_on": [ValueError, ConfigurationError],
    },
)
async def backfill_sections_command(
    input_data: BackfillSectionsInput,
) -> BackfillSectionsOutput:
    """
    Orchestrator: fan out build_sections for all existing sources that:
    - Have a .pdf file_path (may be deleted; build_sections handles that gracefully), OR
    - Have full_text that looks like Docling-structured markdown (heading markers present).

    Skips sources that already have source_section rows.
    """
    start_time = time.time()

    try:
        import re

        heading_re = re.compile(r"^#{1,6}\s+", re.MULTILINE)

        sources_raw = await repo_query("SELECT id, asset, full_text FROM source")

        sources_found = 0
        jobs_submitted = 0

        for row in sources_raw:
            source_id = str(row["id"])
            asset = row.get("asset") or {}
            file_path = ""
            if isinstance(asset, dict):
                file_path = asset.get("file_path") or ""

            full_text = row.get("full_text") or ""

            # Qualify: .pdf extension OR markdown headings present in full_text
            is_pdf = file_path.lower().endswith(".pdf")
            has_headings = bool(heading_re.search(full_text[:5000]))  # peek at first 5k chars
            if not (is_pdf or has_headings):
                continue

            sources_found += 1

            # Skip if sections already exist
            existing = await repo_query(
                "SELECT count() as n FROM source_section WHERE source = $sid GROUP ALL",
                {"sid": ensure_record_id(source_id)},
            )
            if existing and existing[0].get("n", 0) > 0:
                logger.debug(f"Source {source_id} already has sections — skipping")
                continue

            try:
                cmd_id = submit_command(
                    "open_notebook", "build_sections", {"source_id": source_id}
                )
                logger.info(f"Submitted build_sections for {source_id}: {cmd_id}")
                jobs_submitted += 1
            except Exception as exc:
                logger.warning(f"Failed to submit build_sections for {source_id}: {exc}")

        processing_time = time.time() - start_time
        logger.info(
            f"backfill_sections: {sources_found} candidates, {jobs_submitted} jobs submitted "
            f"in {processing_time:.2f}s"
        )
        return BackfillSectionsOutput(
            success=True,
            sources_found=sources_found,
            jobs_submitted=jobs_submitted,
            processing_time=processing_time,
        )

    except Exception as exc:
        processing_time = time.time() - start_time
        logger.error(f"backfill_sections failed: {exc}")
        raise
