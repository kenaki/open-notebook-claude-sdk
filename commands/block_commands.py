"""Block-build command for the PDF block substrate (db-design.md §4).

``build_blocks`` is the idempotent, zero-blackout write path that turns a PDF
into a typed :class:`~open_notebook.parsers.base` block substrate and wires the
rest of the ingest lifecycle:

1. GATE     — skip if a ``ready`` ``source_parse`` header already exists for the
              same ``(parser_name, parser_version, content_hash=sha256(pdf))``.
2. HEADER   — ``gen = max(existing) + 1``; create ``source_parse:[k, gen]``
              ``status='building'``; set ``source.parse_status='parsing'``.
3. PARSE    — ``DoclingBlockParser.parse`` off the event loop
              (``asyncio.to_thread``) + shared ``finalize()``.
4. INSERT   — ``blocks.bulk_insert_blocks`` (explicit composite RecordIDs,
              idempotent on crash+retry). The gen is INVISIBLE until the flip.
5. FINALIZE — stamp the header: ``block_count``, ``page_count``, ``pages``,
              ``page_index``, ``section_index``, ``status='ready'``.
6. FLIP     — single statement on ``source``: ``parse_generation``,
              ``parse_status='embedding'``, parser fields.
6b. MD REGEN (Decision #14) — regenerate ``source.full_text`` via
              ``blocks_to_markdown`` + ``source.page_map`` via
              ``page_map_from_blocks`` (so $$latex$$ + ``block://`` figure refs
              reach chat context / search / transformations / the content tab),
              resubmit ``build_sections`` (REPLACE semantics — it deletes
              existing rows first) so sections rebuild from the rich markdown,
              then submit ``embed_source`` (completes the lifecycle → ``ready``
              in B4). Re-anchor + old-gen cleanup is B5 — until it lands old
              generations are left in place.
9. FAILURE  — pre-flip: partial gen dropped, header ``failed`` + error, source
              ``parse_status='failed'``; the live gen is never touched.
              ``ValueError`` / ``ConfigurationError`` are permanent (no retry);
              transient exceptions retry (≤5). On entry, orphaned ``building``
              generations from crashed prior runs are swept.
"""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import List, Optional

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command, submit_command

from open_notebook.database.repository import (
    ensure_record_id,
    repo_insert,
    repo_query,
    repo_update,
)
from open_notebook.domain import blocks
from open_notebook.domain.blocks import PARSE_TABLE, block_rid, parse_rid
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import ConfigurationError
from open_notebook.parsers.base import blocks_to_markdown, finalize
from open_notebook.parsers.docling_parser import (
    DoclingBlockParser,
    page_map_from_blocks,
)
from open_notebook.utils.block_images import extract_block_images
from open_notebook.utils.job_progress import report_job_progress


# ---------------------------------------------------------------------------
# Pydantic I/O models
# ---------------------------------------------------------------------------


class BuildBlocksInput(CommandInput):
    source_id: str
    # Explicit re-parse (POST /sources/{id}/reparse, C2): bypass the content-hash
    # gate so an unchanged file with the same parser version still builds a new gen.
    force: bool = False


class BuildBlocksOutput(CommandOutput):
    success: bool
    source_id: str
    gen: Optional[int] = None
    block_count: int = 0
    skipped: bool = False
    processing_time: float = 0.0
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src_key(source_id: str) -> str:
    """Bare source key from ``source:<key>`` (or a key passed straight through)."""
    s = str(source_id)
    return s.split(":", 1)[1] if ":" in s else s


def src_key_from(source: Optional[Source]) -> Optional[str]:
    """Best-effort src_key for the failure path (source may be None)."""
    if source is None or source.id is None:
        return None
    return _src_key(str(source.id))


def _sha256_file(path: str) -> str:
    """Streaming sha256 of the PDF bytes — the idempotency-key member."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def _sweep_orphan_building(src_key: str) -> List[int]:
    """Remove orphaned ``building`` generations left by crashed prior runs
    (db-design §4 step 9). Only ``building`` headers are swept — ``ready`` (live)
    and ``superseded`` gens are preserved; B5 owns old-gen cleanup."""
    swept: List[int] = []
    for header in await blocks.list_parse_headers(src_key):
        if header.status == "building":
            await blocks.delete_generation(src_key, header.gen)
            await repo_query(
                f"DELETE {PARSE_TABLE}:[$k, $g];",
                {"k": src_key, "g": header.gen},
            )
            swept.append(header.gen)
    if swept:
        logger.info(f"build_blocks: swept orphan building gens {swept} for {src_key}")
    return swept


def _block_record(src_key: str, gen: int, source_rid, block) -> dict:
    """One ``document_block`` insert row with an explicit composite RecordID."""
    return {
        "id": block_rid(src_key, gen, block.seq),
        "source": source_rid,
        "gen": gen,
        "seq": block.seq,
        "page": block.page,
        "type": block.type.value,
        "text": block.text,
        "latex": block.latex,
        "image_ref": block.image_ref,
        "bbox": block.bbox.as_list() if block.bbox else None,
        "parent_seq": block.parent_seq,
        "level": block.level,
        "subtree_end": block.subtree_end,
        "section_path": list(block.section_path or []),
        "confidence": block.confidence,
        "table_data": block.table_data,
    }


async def _mark_failed(
    source: Optional[Source],
    src_key: Optional[str],
    gen: Optional[int],
    header_created: bool,
    flipped: bool,
    exc: Exception,
) -> None:
    """Failure cleanup (db-design §4 step 9).

    Pre-flip: drop the partial (never-live) generation's blocks, mark its header
    ``failed`` + error, and set ``source.parse_status='failed'`` — the live gen
    is never touched. Post-flip the new gen IS live, so nothing is deleted; the
    error is only logged. Every step is best-effort so cleanup never masks the
    original error.
    """
    if flipped:
        logger.error(f"build_blocks: post-flip error (live gen {gen} kept): {exc!r}")
        return
    if src_key is not None and header_created and gen is not None:
        try:
            await blocks.delete_generation(src_key, gen)
        except Exception as inner:
            logger.debug(f"build_blocks: partial-gen cleanup skipped: {inner!r}")
        try:
            await repo_update(
                PARSE_TABLE,
                parse_rid(src_key, gen),
                {"status": "failed", "error": str(exc)[:1000]},
            )
        except Exception as inner:
            logger.debug(f"build_blocks: header-failed mark skipped: {inner!r}")
    if source is not None and source.id is not None:
        try:
            await repo_update("source", str(source.id), {"parse_status": "failed"})
        except Exception as inner:
            logger.debug(f"build_blocks: source parse_status='failed' skipped: {inner!r}")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@command(
    "build_blocks",
    app="open_notebook",
    retry={
        "max_attempts": 5,
        "wait_strategy": "exponential_jitter",
        "wait_min": 1,
        "wait_max": 60,
        "stop_on": [ValueError, ConfigurationError],
        "retry_log_level": "debug",
    },
)
async def build_blocks_command(input_data: BuildBlocksInput) -> BuildBlocksOutput:
    """Build the typed block substrate for one PDF source (db-design §4)."""
    start_time = time.time()
    job_id = (
        str(input_data.execution_context.command_id)
        if input_data.execution_context
        else None
    )
    source_id = input_data.source_id

    source: Optional[Source] = None
    gen: Optional[int] = None
    header_created = False
    flipped = False

    try:
        source = await Source.get(source_id)
        if not source:
            raise ValueError(f"Source '{source_id}' not found")

        file_path = source.asset.file_path if source.asset else None
        if not file_path or not Path(file_path).exists():
            raise ValueError(
                f"Source '{source_id}' has no readable PDF file to parse "
                f"(file_path={file_path!r})"
            )

        src_key = _src_key(str(source.id))
        source_rid = ensure_record_id(source.id)

        # Startup hygiene: clear any orphaned 'building' gens (crashed runs).
        await _sweep_orphan_building(src_key)

        # ---- 1. GATE -----------------------------------------------------
        content_hash = _sha256_file(file_path)
        parser = DoclingBlockParser()
        headers = await blocks.list_parse_headers(src_key)
        for header in headers:
            if (
                not input_data.force
                and header.status == "ready"
                and header.parser_name == parser.parser_name
                and header.parser_version == parser.parser_version
                and header.content_hash == content_hash
            ):
                logger.info(
                    f"build_blocks: gate skip for {source_id} — ready gen "
                    f"{header.gen} matches ({parser.parser_version})"
                )
                return BuildBlocksOutput(
                    success=True,
                    source_id=source_id,
                    gen=header.gen,
                    block_count=header.block_count or 0,
                    skipped=True,
                    processing_time=time.time() - start_time,
                )

        # ---- 2. HEADER (status='building') -------------------------------
        gen = (max((h.gen for h in headers), default=0)) + 1
        await repo_insert(
            PARSE_TABLE,
            [
                {
                    "id": parse_rid(src_key, gen),
                    "source": source_rid,
                    "gen": gen,
                    "parser_name": parser.parser_name,
                    "parser_version": parser.parser_version,
                    "status": "building",
                    "content_hash": content_hash,
                }
            ],
        )
        header_created = True
        await repo_update("source", str(source.id), {"parse_status": "parsing"})

        # ---- 3. PARSE (off the event loop) + finalize --------------------
        await report_job_progress(job_id, "Parsing blocks", gen=gen)
        result = await asyncio.to_thread(parser.parse, Path(file_path))
        finalized = finalize(result)

        # ---- 3b. RASTERIZE figure/table crops (B3, db-design §4 step 3) ---
        # Sets image_ref on figure/table blocks (relative to UPLOADS_FOLDER);
        # per-block failures degrade to image_ref=None and never abort the parse.
        await asyncio.to_thread(
            extract_block_images, Path(file_path), finalized.blocks, src_key, gen
        )

        # ---- 4. INSERT blocks (invisible until the flip) -----------------
        await report_job_progress(
            job_id, "Persisting blocks", gen=gen, blocks=len(finalized.blocks)
        )
        records = [
            _block_record(src_key, gen, source_rid, b) for b in finalized.blocks
        ]
        inserted = await blocks.bulk_insert_blocks(records)

        # ---- 5. FINALIZE header (status='ready') -------------------------
        await repo_update(
            PARSE_TABLE,
            parse_rid(src_key, gen),
            {
                "block_count": len(finalized.blocks),
                "page_count": finalized.page_count,
                "pages": [p.model_dump() for p in finalized.pages],
                "page_index": finalized.page_index,
                "section_index": finalized.section_index,
                "status": "ready",
            },
        )

        # ---- 6. FLIP (single statement; readers never see a gap) ---------
        await repo_query(
            "UPDATE $sid SET parse_generation = $gen, parse_status = 'embedding', "
            "parser_name = $pn, parser_version = $pv;",
            {
                "sid": source_rid,
                "gen": gen,
                "pn": parser.parser_name,
                "pv": parser.parser_version,
            },
        )
        flipped = True

        # ---- 6b. MARKDOWN REGEN (Decision #14) ---------------------------
        await report_job_progress(job_id, "Regenerating markdown", gen=gen)
        full_text = blocks_to_markdown(finalized.blocks)
        page_map = page_map_from_blocks(finalized.blocks)
        await repo_update(
            "source",
            str(source.id),
            {"full_text": full_text, "page_map": page_map},
        )

        # Rebuild sections from the rich markdown (build_sections is idempotent —
        # it deletes existing source_section rows before rebuilding → REPLACE).
        try:
            scmd = submit_command(
                "open_notebook", "build_sections", {"source_id": str(source.id)}
            )
            logger.info(
                f"build_blocks: resubmitted build_sections for {source.id}: {scmd}"
            )
        except Exception as exc:  # non-fatal — sections must not block ingest
            logger.warning(
                f"build_blocks: build_sections resubmit failed for {source.id}: {exc}"
            )

        # Chain embedding (completes parse_status → 'ready' in B4).
        try:
            ecmd = submit_command(
                "open_notebook", "embed_source", {"source_id": str(source.id)}
            )
            logger.info(f"build_blocks: submitted embed_source for {source.id}: {ecmd}")
        except Exception as exc:  # non-fatal — surfaced via job tray / retryable
            logger.warning(
                f"build_blocks: embed_source submit failed for {source.id}: {exc}"
            )

        # B5: re-anchor annotations + old-generation cleanup is not landed yet;
        # old generations are intentionally left in place until then.

        processing_time = time.time() - start_time
        logger.info(
            f"build_blocks: gen {gen} ready for {source_id} — {len(finalized.blocks)} "
            f"blocks ({inserted} inserted), {finalized.page_count} pages, "
            f"{len(full_text)} md chars in {processing_time:.2f}s"
        )
        return BuildBlocksOutput(
            success=True,
            source_id=source_id,
            gen=gen,
            block_count=len(finalized.blocks),
            processing_time=processing_time,
        )

    except (ValueError, ConfigurationError) as exc:
        # Permanent failure — mark failed and re-raise (stop_on → no retry).
        await _mark_failed(
            source, src_key_from(source), gen, header_created, flipped, exc
        )
        logger.error(f"build_blocks permanent failure for {source_id}: {exc}")
        raise
    except Exception as exc:
        # Transient failure — mark failed and re-raise (surreal-commands retries).
        await _mark_failed(
            source, src_key_from(source), gen, header_created, flipped, exc
        )
        logger.debug(f"build_blocks transient error for {source_id}: {exc!r}")
        raise
