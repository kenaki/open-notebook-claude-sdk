import asyncio
import time
from pathlib import Path
from typing import Dict, List, Literal, Optional

from loguru import logger
from pydantic import BaseModel
from surreal_commands import CommandInput, CommandOutput, command, submit_command

from open_notebook.ai.models import model_manager
from open_notebook.database.repository import (
    ensure_record_id,
    repo_insert,
    repo_query,
    repo_update,
)
from open_notebook.domain import blocks
from open_notebook.domain.notebook import Note, Source, SourceInsight
from open_notebook.exceptions import ConfigurationError
from open_notebook.utils.chunking import (
    ContentType,
    build_page_char_map,
    build_section_char_map,
    chunk_blocks,
    chunk_text,
    detect_content_type,
    find_chunk_page,
    find_chunk_section,
)
from open_notebook.utils.embedding import generate_embedding, generate_embeddings


def full_model_dump(model):
    if isinstance(model, BaseModel):
        return model.model_dump()
    elif isinstance(model, dict):
        return {k: full_model_dump(v) for k, v in model.items()}
    elif isinstance(model, list):
        return [full_model_dump(item) for item in model]
    else:
        return model


def get_command_id(input_data: CommandInput) -> str:
    """Extract command_id from input_data's execution context, or return 'unknown'."""
    if input_data.execution_context:
        return str(input_data.execution_context.command_id)
    return "unknown"


class RebuildEmbeddingsInput(CommandInput):
    mode: Literal["existing", "all"]
    include_sources: bool = True
    include_notes: bool = True
    include_insights: bool = True


class RebuildEmbeddingsOutput(CommandOutput):
    success: bool
    total_items: int
    jobs_submitted: int  # Count of embedding commands submitted
    failed_submissions: int  # Count of items that failed to submit
    sources_submitted: int = 0
    notes_submitted: int = 0
    insights_submitted: int = 0
    processing_time: float
    error_message: Optional[str] = None


# =============================================================================
# NEW EMBEDDING COMMANDS (Phase 3)
# =============================================================================


class CreateInsightInput(CommandInput):
    """Input for creating a source insight with automatic retry on conflicts."""

    source_id: str
    insight_type: str
    content: str


class CreateInsightOutput(CommandOutput):
    """Output from insight creation command."""

    success: bool
    insight_id: Optional[str] = None
    processing_time: float
    error_message: Optional[str] = None


class EmbedNoteInput(CommandInput):
    """Input for embedding a single note."""

    note_id: str


class EmbedNoteOutput(CommandOutput):
    """Output from note embedding command."""

    success: bool
    note_id: str
    processing_time: float
    error_message: Optional[str] = None


class EmbedInsightInput(CommandInput):
    """Input for embedding a single source insight."""

    insight_id: str


class EmbedInsightOutput(CommandOutput):
    """Output from insight embedding command."""

    success: bool
    insight_id: str
    processing_time: float
    error_message: Optional[str] = None


class EmbedSourceInput(CommandInput):
    """Input for embedding a source (creates multiple chunk embeddings)."""

    source_id: str


class EmbedSourceOutput(CommandOutput):
    """Output from source embedding command."""

    success: bool
    source_id: str
    chunks_created: int
    processing_time: float
    error_message: Optional[str] = None


class BackfillPageNumbersInput(CommandInput):
    """No required inputs — fans out embed_source for existing PDF sources so
    their source_embedding rows get stamped with page_number (Phase3)."""


class BackfillPageNumbersOutput(CommandOutput):
    success: bool
    sources_found: int = 0
    page_maps_extracted: int = 0
    jobs_submitted: int = 0
    processing_time: float
    error_message: Optional[str] = None


class LegacyEmbedSingleItemInput(CommandInput):
    """Input for the pre-1.6 embed_single_item command kept for queued jobs."""

    item_id: str
    item_type: Literal["source", "note", "insight"]


class LegacyEmbedSingleItemOutput(CommandOutput):
    """Output matching the pre-1.6 embed_single_item command shape."""

    success: bool
    item_id: str
    item_type: str
    chunks_created: int = 0
    processing_time: float
    error_message: Optional[str] = None


class LegacyEmbedChunkInput(CommandInput):
    """Input for the pre-1.6 per-chunk embedding command kept for queued jobs."""

    source_id: str
    chunk_index: int
    chunk_text: str


class LegacyEmbedChunkOutput(CommandOutput):
    """Output matching the pre-1.6 embed_chunk command shape."""

    success: bool
    source_id: str
    chunk_index: int
    error_message: Optional[str] = None


class LegacyVectorizeSourceInput(CommandInput):
    """Input for the pre-1.6 vectorize_source command kept for queued jobs."""

    source_id: str


class LegacyVectorizeSourceOutput(CommandOutput):
    """Output matching the pre-1.6 vectorize_source command shape."""

    success: bool
    source_id: str
    total_chunks: int
    jobs_submitted: int
    processing_time: float
    error_message: Optional[str] = None


@command(
    "embed_note",
    app="open_notebook",
    retry={
        "max_attempts": 5,
        "wait_strategy": "exponential_jitter",
        "wait_min": 1,
        "wait_max": 60,
        "stop_on": [
            ValueError,
            ConfigurationError,
        ],  # Don't retry validation/config errors
        "retry_log_level": "debug",
    },
)
async def embed_note_command(input_data: EmbedNoteInput) -> EmbedNoteOutput:
    """
    Generate and store embedding for a single note.

    Uses the unified embedding pipeline with automatic chunking and mean pooling
    for notes that exceed the chunk size limit.

    Flow:
    1. Load Note by ID
    2. Generate embedding via generate_embedding() (auto-chunks + mean pools if needed)
    3. UPSERT note embedding in database

    Retry Strategy:
    - Retries up to 5 times for transient failures (network, timeout, etc.)
    - Uses exponential-jitter backoff (1-60s)
    - Does NOT retry permanent failures (ValueError for validation errors)
    """
    start_time = time.time()

    try:
        logger.info(f"Starting embedding for note: {input_data.note_id}")

        # 1. Load note
        note = await Note.get(input_data.note_id)
        if not note:
            raise ValueError(f"Note '{input_data.note_id}' not found")

        if not note.content or not note.content.strip():
            raise ValueError(f"Note '{input_data.note_id}' has no content to embed")

        # 2. Generate embedding (auto-chunks + mean pools if needed)
        # Notes are typically markdown content
        cmd_id = get_command_id(input_data)
        embedding = await generate_embedding(
            note.content, content_type=ContentType.MARKDOWN, command_id=cmd_id
        )

        # 3. UPSERT embedding into note record
        await repo_query(
            "UPDATE $note_id SET embedding = $embedding",
            {
                "note_id": ensure_record_id(input_data.note_id),
                "embedding": embedding,
            },
        )

        processing_time = time.time() - start_time
        logger.info(
            f"Successfully embedded note {input_data.note_id} in {processing_time:.2f}s"
        )

        return EmbedNoteOutput(
            success=True,
            note_id=input_data.note_id,
            processing_time=processing_time,
        )

    except ValueError as e:
        # Permanent failure - don't retry
        processing_time = time.time() - start_time
        cmd_id = get_command_id(input_data)
        logger.error(
            f"Failed to embed note {input_data.note_id} (command: {cmd_id}): {e}"
        )
        return EmbedNoteOutput(
            success=False,
            note_id=input_data.note_id,
            processing_time=processing_time,
            error_message=str(e),
        )
    except Exception as e:
        # Transient failure - will be retried (surreal-commands logs final failure)
        cmd_id = get_command_id(input_data)
        logger.debug(
            f"Transient error embedding note {input_data.note_id} "
            f"(command: {cmd_id}): {e}"
        )
        raise


@command(
    "embed_insight",
    app="open_notebook",
    retry={
        "max_attempts": 5,
        "wait_strategy": "exponential_jitter",
        "wait_min": 1,
        "wait_max": 60,
        "stop_on": [
            ValueError,
            ConfigurationError,
        ],  # Don't retry validation/config errors
        "retry_log_level": "debug",
    },
)
async def embed_insight_command(input_data: EmbedInsightInput) -> EmbedInsightOutput:
    """
    Generate and store embedding for a single source insight.

    Uses the unified embedding pipeline with automatic chunking and mean pooling
    for insights that exceed the chunk size limit.

    Flow:
    1. Load SourceInsight by ID
    2. Generate embedding via generate_embedding() (auto-chunks + mean pools if needed)
    3. UPSERT insight embedding in database

    Retry Strategy:
    - Retries up to 5 times for transient failures (network, timeout, etc.)
    - Uses exponential-jitter backoff (1-60s)
    - Does NOT retry permanent failures (ValueError for validation errors)
    """
    start_time = time.time()

    try:
        logger.info(f"Starting embedding for insight: {input_data.insight_id}")

        # 1. Load insight
        insight = await SourceInsight.get(input_data.insight_id)
        if not insight:
            raise ValueError(f"Insight '{input_data.insight_id}' not found")

        if not insight.content or not insight.content.strip():
            raise ValueError(
                f"Insight '{input_data.insight_id}' has no content to embed"
            )

        # 2. Generate embedding (auto-chunks + mean pools if needed)
        # Insights are typically markdown content (generated by LLM)
        cmd_id = get_command_id(input_data)
        embedding = await generate_embedding(
            insight.content, content_type=ContentType.MARKDOWN, command_id=cmd_id
        )

        # 3. UPSERT embedding into insight record
        await repo_query(
            "UPDATE $insight_id SET embedding = $embedding",
            {
                "insight_id": ensure_record_id(input_data.insight_id),
                "embedding": embedding,
            },
        )

        processing_time = time.time() - start_time
        logger.info(
            f"Successfully embedded insight {input_data.insight_id} in {processing_time:.2f}s"
        )

        return EmbedInsightOutput(
            success=True,
            insight_id=input_data.insight_id,
            processing_time=processing_time,
        )

    except ValueError as e:
        # Permanent failure - don't retry
        processing_time = time.time() - start_time
        cmd_id = get_command_id(input_data)
        logger.error(
            f"Failed to embed insight {input_data.insight_id} (command: {cmd_id}): {e}"
        )
        return EmbedInsightOutput(
            success=False,
            insight_id=input_data.insight_id,
            processing_time=processing_time,
            error_message=str(e),
        )
    except Exception as e:
        # Transient failure - will be retried (surreal-commands logs final failure)
        cmd_id = get_command_id(input_data)
        logger.debug(
            f"Transient error embedding insight {input_data.insight_id} "
            f"(command: {cmd_id}): {e}"
        )
        raise


@command(
    "embed_source",
    app="open_notebook",
    retry={
        "max_attempts": 5,
        "wait_strategy": "exponential_jitter",
        "wait_min": 1,
        "wait_max": 60,
        "stop_on": [
            ValueError,
            ConfigurationError,
        ],  # Don't retry validation/config errors
        "retry_log_level": "debug",
    },
)
async def embed_source_command(input_data: EmbedSourceInput) -> EmbedSourceOutput:
    """
    Generate and store embeddings for a source document.

    Creates multiple chunk embeddings stored in the source_embedding table.

    Two chunking paths (B4, db-design §2.3 / §4 step 7):
    - **Block path** — a source with a ready block generation
      (``parse_generation`` + a ``source_parse`` header ``status='ready'``) packs
      WHOLE typed blocks in seq order via ``chunk_blocks`` → exact
      ``[block_start, block_end]`` + ``page_number`` per chunk, ``gen`` =
      ``parse_generation``. Retires the lossy 80-char page heuristic.
    - **Legacy path** — no blocks: content-type aware ``chunk_text`` with the
      section/page-map heuristics unchanged; rows get ``gen = max(existing)+1``.

    Both paths are **no-blackout** (Decision #10): new-gen rows are bulk-INSERTed
    FIRST, then old rows (``gen IS NONE OR gen != new``) are DELETEd — so
    ``fn::vector_search`` never sees a zero-embedding window during a re-embed.

    Retry Strategy:
    - Retries up to 5 times for transient failures (network, timeout, etc.)
    - Uses exponential-jitter backoff (1-60s)
    - Does NOT retry permanent failures (ValueError for validation errors)
    """
    start_time = time.time()

    try:
        logger.info(f"Starting embedding for source: {input_data.source_id}")

        # 1. Load source
        source = await Source.get(input_data.source_id)
        if not source:
            raise ValueError(f"Source '{input_data.source_id}' not found")

        if not source.full_text or not source.full_text.strip():
            raise ValueError(f"Source '{input_data.source_id}' has no text to embed")

        sid = ensure_record_id(input_data.source_id)
        cmd_id = get_command_id(input_data)

        # Decide the chunking path: block-aware when a ready parse generation
        # exists, else the legacy full_text path.
        src_key = str(source.id).split(":", 1)[1] if ":" in str(source.id) else str(source.id)
        parse_gen = source.parse_generation
        parse_header = None
        if parse_gen:
            try:
                parse_header = await blocks.get_parse_header(src_key, parse_gen)
            except Exception as header_exc:  # pragma: no cover - defensive
                logger.debug(f"Parse-header lookup failed: {header_exc!r}")
                parse_header = None
        use_block_path = bool(
            parse_gen and parse_header and parse_header.status == "ready"
        )

        if use_block_path:
            # --- BLOCK PATH (db-design §2.3 / §4 step 7) ---
            hi = (
                parse_header.block_count
                if parse_header.block_count is not None
                else 10_000_000
            )
            block_rows = await blocks.get_range(src_key, parse_gen, 0, hi)
            block_chunks = chunk_blocks(block_rows)
            chunks = [bc["content"] for bc in block_chunks]
            total_chunks = len(chunks)
            logger.info(
                f"Created {total_chunks} block chunks for source "
                f"{input_data.source_id} (gen {parse_gen}, {len(block_rows)} blocks)"
            )
            if total_chunks == 0:
                raise ValueError("No chunks created after packing blocks")

            embeddings = await generate_embeddings(chunks, command_id=cmd_id)
            if len(embeddings) != len(chunks):
                raise ValueError(
                    f"Embedding count mismatch: got {len(embeddings)} embeddings "
                    f"for {len(chunks)} chunks"
                )

            embed_gen = parse_gen
            records = [
                {
                    "source": sid,
                    "order": idx,
                    "content": bc["content"],
                    "embedding": embedding,
                    "section": None,
                    "page_number": bc["page_number"],
                    "block_start": bc["block_start"],
                    "block_end": bc["block_end"],
                    "gen": embed_gen,
                }
                for idx, (bc, embedding) in enumerate(zip(block_chunks, embeddings))
            ]
        else:
            # --- LEGACY PATH (content-type chunking + page/section heuristics) ---
            file_path = source.asset.file_path if source.asset else None
            content_type = detect_content_type(source.full_text, file_path)
            logger.debug(f"Detected content type: {content_type.value}")

            chunks = chunk_text(source.full_text, content_type=content_type)
            total_chunks = len(chunks)

            chunk_sizes = [len(c) for c in chunks]
            logger.info(
                f"Created {total_chunks} chunks for source {input_data.source_id} "
                f"(sizes: min={min(chunk_sizes) if chunk_sizes else 0}, "
                f"max={max(chunk_sizes) if chunk_sizes else 0}, "
                f"avg={sum(chunk_sizes) // len(chunk_sizes) if chunk_sizes else 0} chars)"
            )

            if total_chunks == 0:
                raise ValueError("No chunks created after splitting text")

            logger.debug(f"Generating embeddings for {total_chunks} chunks")
            embeddings = await generate_embeddings(chunks, command_id=cmd_id)

            if len(embeddings) != len(chunks):
                raise ValueError(
                    f"Embedding count mismatch: got {len(embeddings)} embeddings "
                    f"for {len(chunks)} chunks"
                )

            # A3: stamp section on each record (None when sections not yet built)
            source_sections_raw = await repo_query(
                # `order` is a reserved word in SurrealQL: `ORDER BY order` parses
                # ("Missing order idiom") ONLY when `order` is also in the SELECT
                # projection — backticks and `ASC` do NOT help (verified against
                # the live DB). This is why get_outline works and this query
                # didn't: project `order` so the ORDER BY can resolve it.
                "SELECT id, content, order FROM source_section WHERE source = $sid ORDER BY order",
                {"sid": sid},
            )
            section_map = (
                build_section_char_map(source.full_text, source_sections_raw)
                if source_sections_raw and source.full_text
                else []
            )
            logger.debug(
                f"Section map: {len(section_map)} entries for {total_chunks} chunks"
            )

            # Phase3: stamp page_number on each record from the source's persisted
            # page_map (A2 provenance). None when the source has no page_map
            # (non-PDF, pre-Docling, or PyMuPDF-fallback) or a chunk can't locate.
            page_char_map = (
                build_page_char_map(source.full_text, source.page_map)
                if source.page_map and source.full_text
                else []
            )
            logger.debug(
                f"Page map: {len(page_char_map)} entries for {total_chunks} chunks"
            )

            # Legacy rows still get a monotonic gen so the no-blackout
            # insert-first/delete-after ordering works for them too (Decision #10).
            existing_gen_rows = await repo_query(
                "SELECT gen FROM source_embedding WHERE source = $sid", {"sid": sid}
            )
            embed_gen = (
                max(
                    (
                        r.get("gen")
                        for r in existing_gen_rows
                        if r.get("gen") is not None
                    ),
                    default=0,
                )
                + 1
            )

            records = []
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                section_rid = None
                if section_map and source.full_text:
                    sec_id = find_chunk_section(chunk, source.full_text, section_map)
                    if sec_id:
                        section_rid = ensure_record_id(sec_id)
                page_number = None
                if page_char_map and source.full_text:
                    page_number = find_chunk_page(
                        chunk, source.full_text, page_char_map
                    )
                records.append(
                    {
                        "source": sid,
                        "order": idx,
                        "content": chunk,
                        "embedding": embedding,
                        "section": section_rid,
                        "page_number": page_number,
                        "gen": embed_gen,
                    }
                )

        # No-blackout re-embed (Decision #10): INSERT new-gen rows FIRST, THEN
        # delete every stale row (legacy NONE gen + any earlier gen). Readers of
        # fn::vector_search never see a zero-embedding window.
        logger.debug(f"Inserting {len(records)} source_embedding records")
        await repo_insert("source_embedding", records)
        await repo_query(
            "DELETE source_embedding WHERE source = $sid "
            "AND (gen IS NONE OR gen != $gen)",
            {"sid": sid, "gen": embed_gen},
        )

        # Complete the parse lifecycle: embedding -> ready.
        if source.parse_status == "embedding":
            await repo_update("source", str(source.id), {"parse_status": "ready"})

        processing_time = time.time() - start_time
        logger.info(
            f"Successfully embedded source {input_data.source_id}: "
            f"{total_chunks} chunks in {processing_time:.2f}s"
        )

        return EmbedSourceOutput(
            success=True,
            source_id=input_data.source_id,
            chunks_created=total_chunks,
            processing_time=processing_time,
        )

    except ValueError as e:
        # Permanent failure - don't retry
        processing_time = time.time() - start_time
        cmd_id = get_command_id(input_data)
        logger.error(
            f"Failed to embed source {input_data.source_id} (command: {cmd_id}): {e}"
        )
        return EmbedSourceOutput(
            success=False,
            source_id=input_data.source_id,
            chunks_created=0,
            processing_time=processing_time,
            error_message=str(e),
        )
    except Exception as e:
        # Transient failure - will be retried (surreal-commands logs final failure)
        cmd_id = get_command_id(input_data)
        logger.debug(
            f"Transient error embedding source {input_data.source_id} "
            f"(command: {cmd_id}): {e}"
        )
        raise


@command(
    "backfill_page_numbers",
    app="open_notebook",
    retry={
        "max_attempts": 1,
        "stop_on": [ValueError, ConfigurationError],
    },
)
async def backfill_page_numbers_command(
    input_data: BackfillPageNumbersInput,
) -> BackfillPageNumbersOutput:
    """
    Phase3 one-time backfill: stamp page_number on existing source_embedding rows.

    Orchestrator that, for every source that is a PDF and/or already has a
    persisted page_map, resolves page provenance and re-submits embed_source
    (which reads source.page_map and stamps page_number per chunk).

    Provenance resolution order (per source):
      1. source.page_map already persisted → re-embed as-is.
      2. page_map null + the .pdf asset file still exists → re-extract via A2's
         _extract_docling_page_map (PyMuPDF fallback lives inside content
         extraction; here we call Docling directly), persist it, then re-embed.
      3. Neither (no page_map, file gone / not a PDF) → leave page_number null,
         never guess, and skip the needless re-embed.

    Run manually: submit_command("open_notebook", "backfill_page_numbers", {}).
    """
    start_time = time.time()

    try:
        logger.info("backfill_page_numbers started")

        sources_raw = await repo_query(
            "SELECT id, asset, page_map, full_text FROM source"
        )

        sources_found = 0
        page_maps_extracted = 0
        jobs_submitted = 0

        for row in sources_raw or []:
            source_id = str(row["id"])
            asset = row.get("asset") or {}
            file_path = ""
            if isinstance(asset, dict):
                file_path = asset.get("file_path") or ""
            is_pdf = file_path.lower().endswith(".pdf")
            page_map = row.get("page_map")

            # Qualify: already has provenance, or is a PDF we might re-extract.
            if not (page_map or is_pdf):
                continue
            sources_found += 1

            # (2) Re-extract + persist when page_map is missing but the PDF exists.
            if not page_map and is_pdf and file_path and Path(file_path).exists():
                try:
                    from open_notebook.graphs.source import _extract_docling_page_map

                    _ft, extracted = await asyncio.to_thread(
                        _extract_docling_page_map, file_path
                    )
                    if extracted:
                        source = await Source.get(source_id)
                        if source:
                            source.page_map = extracted
                            await source.save()
                            page_map = extracted
                            page_maps_extracted += 1
                            logger.info(
                                f"Re-extracted page_map for {source_id}: "
                                f"{len(extracted)} blocks"
                            )
                except Exception as exc:
                    logger.warning(
                        f"page_map re-extraction failed for {source_id}: {exc!r} "
                        "— leaving page_number null"
                    )

            # (3) Still no provenance → skip; re-embedding would stamp nothing.
            if not page_map:
                logger.debug(
                    f"Source {source_id} has no page_map — skipping (page_number stays null)"
                )
                continue

            # (1)/(2) provenance available → re-embed to stamp page_number.
            try:
                cmd_id = submit_command(
                    "open_notebook", "embed_source", {"source_id": source_id}
                )
                logger.info(f"Submitted embed_source for {source_id}: {cmd_id}")
                jobs_submitted += 1
            except Exception as exc:
                logger.warning(f"Failed to submit embed_source for {source_id}: {exc}")

        processing_time = time.time() - start_time
        logger.info(
            f"backfill_page_numbers: {sources_found} candidates, "
            f"{page_maps_extracted} page_maps re-extracted, "
            f"{jobs_submitted} embed jobs submitted in {processing_time:.2f}s"
        )
        return BackfillPageNumbersOutput(
            success=True,
            sources_found=sources_found,
            page_maps_extracted=page_maps_extracted,
            jobs_submitted=jobs_submitted,
            processing_time=processing_time,
        )

    except Exception as exc:
        processing_time = time.time() - start_time
        logger.error(f"backfill_page_numbers failed: {exc}")
        logger.exception(exc)
        return BackfillPageNumbersOutput(
            success=False,
            processing_time=processing_time,
            error_message=str(exc),
        )


@command(
    "embed_single_item",
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
async def legacy_embed_single_item_command(
    input_data: LegacyEmbedSingleItemInput,
) -> LegacyEmbedSingleItemOutput:
    """
    Compatibility handler for pre-1.6 queued embed_single_item jobs.

    New code submits embed_source, embed_note, or embed_insight directly. This
    alias lets workers drain older queues after an upgrade.
    """
    start_time = time.time()

    try:
        logger.info(
            f"Processing legacy embed_single_item for "
            f"{input_data.item_type}: {input_data.item_id}"
        )

        if input_data.item_type == "source":
            result = await embed_source_command(
                EmbedSourceInput(
                    source_id=input_data.item_id,
                    execution_context=input_data.execution_context,
                )
            )
            chunks_created = result.chunks_created
        elif input_data.item_type == "note":
            result = await embed_note_command(
                EmbedNoteInput(
                    note_id=input_data.item_id,
                    execution_context=input_data.execution_context,
                )
            )
            chunks_created = 0
        elif input_data.item_type == "insight":
            result = await embed_insight_command(
                EmbedInsightInput(
                    insight_id=input_data.item_id,
                    execution_context=input_data.execution_context,
                )
            )
            chunks_created = 0
        else:
            raise ValueError(f"Invalid item_type: {input_data.item_type}")

        return LegacyEmbedSingleItemOutput(
            success=result.success,
            item_id=input_data.item_id,
            item_type=input_data.item_type,
            chunks_created=chunks_created,
            processing_time=time.time() - start_time,
            error_message=result.error_message,
        )

    except ValueError as e:
        processing_time = time.time() - start_time
        logger.error(
            f"Failed legacy embed_single_item for "
            f"{input_data.item_type} {input_data.item_id}: {e}"
        )
        return LegacyEmbedSingleItemOutput(
            success=False,
            item_id=input_data.item_id,
            item_type=input_data.item_type,
            processing_time=processing_time,
            error_message=str(e),
        )
    except Exception as e:
        logger.debug(
            f"Transient error in legacy embed_single_item for "
            f"{input_data.item_type} {input_data.item_id}: {e}"
        )
        raise


@command(
    "embed_chunk",
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
async def legacy_embed_chunk_command(
    input_data: LegacyEmbedChunkInput,
) -> LegacyEmbedChunkOutput:
    """
    Compatibility handler for pre-1.6 queued embed_chunk jobs.

    The legacy vectorizer stored the full chunk payload in each job. Keeping this
    command registered prevents upgraded workers from crashing on stale queues.
    """
    try:
        logger.debug(
            f"Processing legacy chunk {input_data.chunk_index} "
            f"for source {input_data.source_id}"
        )

        cmd_id = get_command_id(input_data)
        embedding = await generate_embedding(
            input_data.chunk_text,
            content_type=ContentType.PLAIN,
            command_id=cmd_id,
        )

        await repo_query(
            """
            CREATE source_embedding CONTENT {
                "source": $source_id,
                "order": $order,
                "content": $content,
                "embedding": $embedding,
            };
            """,
            {
                "source_id": ensure_record_id(input_data.source_id),
                "order": input_data.chunk_index,
                "content": input_data.chunk_text,
                "embedding": embedding,
            },
        )

        return LegacyEmbedChunkOutput(
            success=True,
            source_id=input_data.source_id,
            chunk_index=input_data.chunk_index,
        )

    except ValueError as e:
        logger.error(
            f"Failed legacy embed_chunk for source {input_data.source_id} "
            f"chunk {input_data.chunk_index}: {e}"
        )
        return LegacyEmbedChunkOutput(
            success=False,
            source_id=input_data.source_id,
            chunk_index=input_data.chunk_index,
            error_message=str(e),
        )
    except Exception as e:
        logger.debug(
            f"Transient error in legacy embed_chunk for source "
            f"{input_data.source_id} chunk {input_data.chunk_index}: {e}"
        )
        raise


@command("vectorize_source", app="open_notebook", retry=None)
async def legacy_vectorize_source_command(
    input_data: LegacyVectorizeSourceInput,
) -> LegacyVectorizeSourceOutput:
    """
    Compatibility handler for pre-1.6 queued vectorize_source jobs.

    The old command submitted one job per chunk. Current embed_source does the
    same source embedding work in one batch-aware command.
    """
    start_time = time.time()

    try:
        logger.info(f"Processing legacy vectorize_source for {input_data.source_id}")
        result = await embed_source_command(
            EmbedSourceInput(
                source_id=input_data.source_id,
                execution_context=input_data.execution_context,
            )
        )
        jobs_submitted = 1 if result.success else 0

        return LegacyVectorizeSourceOutput(
            success=result.success,
            source_id=input_data.source_id,
            total_chunks=result.chunks_created,
            jobs_submitted=jobs_submitted,
            processing_time=time.time() - start_time,
            error_message=result.error_message,
        )

    except ValueError as e:
        processing_time = time.time() - start_time
        logger.error(f"Failed legacy vectorize_source for {input_data.source_id}: {e}")
        return LegacyVectorizeSourceOutput(
            success=False,
            source_id=input_data.source_id,
            total_chunks=0,
            jobs_submitted=0,
            processing_time=processing_time,
            error_message=str(e),
        )
    except Exception as e:
        logger.debug(
            f"Transient error in legacy vectorize_source for "
            f"{input_data.source_id}: {e}"
        )
        raise


@command(
    "create_insight",
    app="open_notebook",
    retry={
        "max_attempts": 5,
        "wait_strategy": "exponential_jitter",
        "wait_min": 1,
        "wait_max": 60,
        "stop_on": [
            ValueError,
            ConfigurationError,
        ],  # Don't retry validation/config errors
        "retry_log_level": "debug",
    },
)
async def create_insight_command(
    input_data: CreateInsightInput,
) -> CreateInsightOutput:
    """
    Create a source insight with automatic retry on transaction conflicts.

    This command wraps the CREATE source_insight operation with retry logic
    to handle SurrealDB transaction conflicts that occur during batch imports
    when multiple parallel transformations try to create insights concurrently.

    Flow:
    1. CREATE source_insight record in database
    2. Submit embed_insight command (fire-and-forget) for async embedding
    3. Return the insight_id

    Retry Strategy:
    - Retries up to 5 times for transient failures (network, timeout, etc.)
    - Uses exponential-jitter backoff (1-60s)
    - Does NOT retry permanent failures (ValueError for validation errors)
    """
    start_time = time.time()

    try:
        logger.info(
            f"Creating insight for source {input_data.source_id}: "
            f"type={input_data.insight_type}"
        )

        # 1. Create insight record in database
        result = await repo_query(
            """
            CREATE source_insight CONTENT {
                "source": $source_id,
                "insight_type": $insight_type,
                "content": $content
            };
            """,
            {
                "source_id": ensure_record_id(input_data.source_id),
                "insight_type": input_data.insight_type,
                "content": input_data.content,
            },
        )

        if not result or len(result) == 0:
            raise ValueError("Failed to create insight - no result returned")

        insight_id = str(result[0].get("id", ""))
        if not insight_id:
            raise ValueError("Failed to create insight - no ID in result")

        # 2. Submit embedding command (fire-and-forget)
        submit_command(
            "open_notebook",
            "embed_insight",
            {"insight_id": insight_id},
        )
        logger.debug(f"Submitted embed_insight command for {insight_id}")

        processing_time = time.time() - start_time
        logger.info(
            f"Successfully created insight {insight_id} for source "
            f"{input_data.source_id} in {processing_time:.2f}s"
        )

        return CreateInsightOutput(
            success=True,
            insight_id=insight_id,
            processing_time=processing_time,
        )

    except ValueError as e:
        # Permanent failure - don't retry
        processing_time = time.time() - start_time
        cmd_id = get_command_id(input_data)
        logger.error(
            f"Failed to create insight for source {input_data.source_id} "
            f"(command: {cmd_id}): {e}"
        )
        return CreateInsightOutput(
            success=False,
            processing_time=processing_time,
            error_message=str(e),
        )
    except Exception as e:
        # Transient failure - will be retried (surreal-commands logs final failure)
        cmd_id = get_command_id(input_data)
        logger.debug(
            f"Transient error creating insight for source {input_data.source_id} "
            f"(command: {cmd_id}): {e}"
        )
        raise


async def collect_items_for_rebuild(
    mode: str,
    include_sources: bool,
    include_notes: bool,
    include_insights: bool,
) -> Dict[str, List[str]]:
    """
    Collect items to rebuild based on mode and include flags.

    Returns:
        Dict with keys: 'sources', 'notes', 'insights' containing lists of item IDs
    """
    items: Dict[str, List[str]] = {"sources": [], "notes": [], "insights": []}

    if include_sources:
        if mode == "existing":
            # Query sources with embeddings (via source_embedding table)
            result = await repo_query(
                """
                RETURN array::distinct(
                    SELECT VALUE source.id
                    FROM source_embedding
                    WHERE embedding != none AND array::len(embedding) > 0
                )
                """
            )
            # RETURN returns the array directly as the result (not nested)
            if result:
                items["sources"] = [str(item) for item in result]
            else:
                items["sources"] = []
        else:  # mode == "all"
            # Query all sources with non-empty content
            result = await repo_query(
                "SELECT id FROM source WHERE full_text != none AND string::trim(full_text) != ''"
            )
            items["sources"] = [str(item["id"]) for item in result] if result else []

        logger.info(f"Collected {len(items['sources'])} sources for rebuild")

    if include_notes:
        if mode == "existing":
            # Query notes with embeddings
            result = await repo_query(
                "SELECT id FROM note WHERE embedding != none AND array::len(embedding) > 0"
            )
        else:  # mode == "all"
            # Query all notes with non-empty content
            result = await repo_query(
                "SELECT id FROM note WHERE content != none AND string::trim(content) != ''"
            )

        items["notes"] = [str(item["id"]) for item in result] if result else []
        logger.info(f"Collected {len(items['notes'])} notes for rebuild")

    if include_insights:
        if mode == "existing":
            # Query insights with embeddings
            result = await repo_query(
                "SELECT id FROM source_insight WHERE embedding != none AND array::len(embedding) > 0"
            )
        else:  # mode == "all"
            # Query all insights with non-empty content
            result = await repo_query(
                "SELECT id FROM source_insight WHERE content != none AND string::trim(content) != ''"
            )

        items["insights"] = [str(item["id"]) for item in result] if result else []
        logger.info(f"Collected {len(items['insights'])} insights for rebuild")

    return items


@command("rebuild_embeddings", app="open_notebook", retry=None)
async def rebuild_embeddings_command(
    input_data: RebuildEmbeddingsInput,
) -> RebuildEmbeddingsOutput:
    """
    Rebuild embeddings for sources, notes, and/or insights.

    This command submits individual embedding jobs for each item:
    - embed_source for sources
    - embed_note for notes
    - embed_insight for insights

    The command returns after submitting all jobs. Actual embedding
    happens asynchronously via the individual commands (which have
    their own retry strategies).

    Retry Strategy:
    - Retries disabled (retry=None) for this coordinator command
    - Individual embed_* commands handle their own retries
    """
    start_time = time.time()

    try:
        logger.info("=" * 60)
        logger.info(f"Starting embedding rebuild with mode={input_data.mode}")
        logger.info(
            f"Include: sources={input_data.include_sources}, notes={input_data.include_notes}, insights={input_data.include_insights}"
        )
        logger.info("=" * 60)

        # Check embedding model availability (fail fast)
        EMBEDDING_MODEL = await model_manager.get_embedding_model()
        if not EMBEDDING_MODEL:
            raise ValueError(
                "No embedding model configured. Please configure one in the Models section."
            )

        logger.info(f"Embedding model configured: {EMBEDDING_MODEL}")

        # Collect items to process (returns IDs only)
        items = await collect_items_for_rebuild(
            input_data.mode,
            input_data.include_sources,
            input_data.include_notes,
            input_data.include_insights,
        )

        total_items = (
            len(items["sources"]) + len(items["notes"]) + len(items["insights"])
        )
        logger.info(f"Total items to rebuild: {total_items}")

        if total_items == 0:
            logger.warning("No items found to rebuild")
            return RebuildEmbeddingsOutput(
                success=True,
                total_items=0,
                jobs_submitted=0,
                failed_submissions=0,
                processing_time=time.time() - start_time,
            )

        # Initialize counters
        sources_submitted = 0
        notes_submitted = 0
        insights_submitted = 0
        failed_submissions = 0

        # Submit embed_source commands for sources
        logger.info(f"\nSubmitting {len(items['sources'])} source embedding jobs...")
        for idx, source_id in enumerate(items["sources"], 1):
            try:
                submit_command(
                    "open_notebook",
                    "embed_source",
                    {"source_id": source_id},
                )
                sources_submitted += 1

                if idx % 50 == 0 or idx == len(items["sources"]):
                    logger.info(
                        f"  Progress: {idx}/{len(items['sources'])} source jobs submitted"
                    )

            except Exception as e:
                logger.error(f"Failed to submit embed_source for {source_id}: {e}")
                failed_submissions += 1

        # Submit embed_note commands for notes
        logger.info(f"\nSubmitting {len(items['notes'])} note embedding jobs...")
        for idx, note_id in enumerate(items["notes"], 1):
            try:
                submit_command(
                    "open_notebook",
                    "embed_note",
                    {"note_id": note_id},
                )
                notes_submitted += 1

                if idx % 50 == 0 or idx == len(items["notes"]):
                    logger.info(
                        f"  Progress: {idx}/{len(items['notes'])} note jobs submitted"
                    )

            except Exception as e:
                logger.error(f"Failed to submit embed_note for {note_id}: {e}")
                failed_submissions += 1

        # Submit embed_insight commands for insights
        logger.info(f"\nSubmitting {len(items['insights'])} insight embedding jobs...")
        for idx, insight_id in enumerate(items["insights"], 1):
            try:
                submit_command(
                    "open_notebook",
                    "embed_insight",
                    {"insight_id": insight_id},
                )
                insights_submitted += 1

                if idx % 50 == 0 or idx == len(items["insights"]):
                    logger.info(
                        f"  Progress: {idx}/{len(items['insights'])} insight jobs submitted"
                    )

            except Exception as e:
                logger.error(f"Failed to submit embed_insight for {insight_id}: {e}")
                failed_submissions += 1

        processing_time = time.time() - start_time
        jobs_submitted = sources_submitted + notes_submitted + insights_submitted

        logger.info("=" * 60)
        logger.info("REBUILD JOBS SUBMITTED")
        logger.info(f"  Total jobs submitted: {jobs_submitted}/{total_items}")
        logger.info(f"  Sources: {sources_submitted}")
        logger.info(f"  Notes: {notes_submitted}")
        logger.info(f"  Insights: {insights_submitted}")
        logger.info(f"  Failed submissions: {failed_submissions}")
        logger.info(f"  Submission time: {processing_time:.2f}s")
        logger.info("  Note: Actual embedding happens asynchronously")
        logger.info("=" * 60)

        return RebuildEmbeddingsOutput(
            success=True,
            total_items=total_items,
            jobs_submitted=jobs_submitted,
            failed_submissions=failed_submissions,
            sources_submitted=sources_submitted,
            notes_submitted=notes_submitted,
            insights_submitted=insights_submitted,
            processing_time=processing_time,
        )

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"Rebuild embeddings failed: {e}")
        logger.exception(e)

        return RebuildEmbeddingsOutput(
            success=False,
            total_items=0,
            jobs_submitted=0,
            failed_submissions=0,
            processing_time=processing_time,
            error_message=str(e),
        )
