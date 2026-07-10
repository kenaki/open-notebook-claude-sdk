import asyncio
import os
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from loguru import logger
from surreal_commands import execute_command_sync

from api.command_service import CommandService
from api.models import SourceCreate, SourceResponse
from api.routers.sources._helpers import source_to_response
from api.upload_utils import UploadTooLargeError, save_uploaded_file
from commands._job_guards import command_in_flight
from commands.source_commands import SourceProcessingInput
from open_notebook.config import UPLOADS_FOLDER
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Asset, Notebook, Source
from open_notebook.domain.transformation import Transformation
from open_notebook.exceptions import InvalidInputError
from pathlib import Path

router = APIRouter()


def parse_source_form_data(
    type: str = Form(...),
    notebook_id: Optional[str] = Form(None),
    notebooks: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    transformations: Optional[str] = Form(None),
    embed: str = Form("false"),
    delete_source: str = Form("false"),
    async_processing: str = Form("false"),
    file: Optional[UploadFile] = File(None),
) -> tuple[SourceCreate, Optional[UploadFile]]:
    """Parse form data into SourceCreate model and return upload file separately."""
    import json

    def str_to_bool(value: str) -> bool:
        return value.lower() in ("true", "1", "yes", "on")

    notebooks_list = None
    if notebooks:
        try:
            notebooks_list = json.loads(notebooks)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in notebooks field: {notebooks}")
            raise ValueError("Invalid JSON in notebooks field")

    transformations_list = []
    if transformations:
        try:
            transformations_list = json.loads(transformations)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in transformations field: {transformations}")
            raise ValueError("Invalid JSON in transformations field")

    try:
        source_data = SourceCreate(
            type=type,
            notebook_id=notebook_id,
            notebooks=notebooks_list,
            url=url,
            content=content,
            title=title,
            file_path=None,
            transformations=transformations_list,
            embed=str_to_bool(embed),
            delete_source=str_to_bool(delete_source),
            async_processing=str_to_bool(async_processing),
        )
    except Exception as e:
        logger.error(f"Failed to create SourceCreate instance: {e}")
        raise

    return source_data, file


# SurrealDB reports optimistic-concurrency failures as plain text on a generic
# exception, so the conflict has to be matched on the message.
_TX_CONFLICT_MARKERS = (
    "read or write conflict",
    "failed transaction",
    "this transaction can be retried",
)


def _is_tx_conflict(exc: BaseException) -> bool:
    """True when ``exc`` is a retriable SurrealDB transaction conflict."""
    return any(marker in str(exc).lower() for marker in _TX_CONFLICT_MARKERS)


async def _link_command_to_source(
    source: Source, command_id: str, attempts: int = 5
) -> None:
    """Point ``source.command`` at ``command_id``, retrying transaction conflicts.

    Two concurrent submits for the same source — a double-clicked Retry — both
    write this row and one loses the optimistic-concurrency check. The write is
    idempotent, so a bounded backoff is all the loser needs.
    """
    for attempt in range(attempts):
        try:
            source.command = ensure_record_id(command_id)
            await source.save()
            return
        except Exception as e:
            if not _is_tx_conflict(e) or attempt == attempts - 1:
                raise
            await asyncio.sleep(0.05 * (2**attempt))


async def _submit_source_command(
    source: Source,
    content_state: dict,
    notebook_ids: Optional[List[str]],
    transformations: List[str],
    embed: bool,
) -> str:
    """Submit a source processing command and update source.command. Returns command_id."""
    import commands.source_commands  # noqa: F401

    command_input = SourceProcessingInput(
        source_id=str(source.id),
        content_state=content_state,
        notebook_ids=notebook_ids,
        transformations=transformations,
        embed=embed,
    )
    command_id = await CommandService.submit_command_job(
        "open_notebook",
        "process_source",
        command_input.model_dump(),
    )

    # The row is live the moment it is submitted — the worker's LIVE query
    # dispatches it regardless of what happens next here. So a failure to link it
    # back must cancel it, or the caller is told "failed to queue" while a full
    # re-parse runs anyway, detached from source.command.
    try:
        await _link_command_to_source(source, command_id)
    except Exception:
        logger.error(
            f"Failed to link command {command_id} to source {source.id}; "
            f"canceling the orphaned job"
        )
        try:
            await CommandService.cancel_command_job(command_id)
        except Exception as cancel_exc:
            logger.error(f"Could not cancel orphaned command {command_id}: {cancel_exc}")
        raise

    return command_id


def _build_content_state(source_data: SourceCreate, file_path: Optional[str]) -> dict[str, Any]:
    """Validate source type fields and return the content_state dict for processing."""
    if source_data.type == "link":
        if not source_data.url:
            raise HTTPException(status_code=400, detail="URL is required for link type")
        return {"url": source_data.url}

    if source_data.type == "upload":
        final_file_path = file_path or source_data.file_path
        if not final_file_path:
            raise HTTPException(
                status_code=400,
                detail="File upload or file_path is required for upload type",
            )
        uploads_resolved = Path(UPLOADS_FOLDER).resolve()
        file_resolved = Path(final_file_path).resolve()
        if not str(file_resolved).startswith(str(uploads_resolved) + os.sep):
            raise HTTPException(
                status_code=400,
                detail="Invalid file path: must be within the uploads directory",
            )
        return {"file_path": final_file_path, "delete_source": source_data.delete_source}

    if source_data.type == "text":
        if not source_data.content:
            raise HTTPException(status_code=400, detail="Content is required for text type")
        return {"content": source_data.content}

    raise HTTPException(
        status_code=400,
        detail="Invalid source type. Must be link, upload, or text",
    )


@router.post("/sources", response_model=SourceResponse)
async def create_source(
    form_data: tuple[SourceCreate, Optional[UploadFile]] = Depends(parse_source_form_data),
):
    """Create a new source with support for both JSON and multipart form data."""
    source_data, upload_file = form_data
    file_path = None

    try:
        for notebook_id in source_data.notebooks or []:
            notebook = await Notebook.get(notebook_id)
            if not notebook:
                raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")

        if upload_file and source_data.type == "upload":
            try:
                file_path = await save_uploaded_file(upload_file)
            except UploadTooLargeError as e:
                logger.warning(f"Upload rejected (too large): {e}")
                raise HTTPException(status_code=413, detail=str(e))
            except OSError as e:
                # Disk-level failure (out of space, permissions) — the server's
                # problem, not the client's.
                logger.error(f"File upload failed (storage error): {e}")
                raise HTTPException(
                    status_code=500,
                    detail="File upload failed: the server could not store the file (disk full or not writable).",
                )
            except Exception as e:
                logger.error(f"File upload failed: {e}")
                raise HTTPException(status_code=400, detail=f"File upload failed: {str(e)}")

        content_state = _build_content_state(source_data, file_path)

        transformation_ids = source_data.transformations or []
        for trans_id in transformation_ids:
            transformation = await Transformation.get(trans_id)
            if not transformation:
                raise HTTPException(status_code=404, detail=f"Transformation {trans_id} not found")

        if source_data.async_processing:
            logger.info("Using async processing path")

            source_asset = None
            if source_data.type == "link":
                source_asset = Asset(url=source_data.url)
            elif source_data.type == "upload":
                source_asset = Asset(file_path=file_path or source_data.file_path)

            source = Source(
                title=source_data.title or "Processing...",
                topics=[],
                asset=source_asset,
            )
            await source.save()

            for notebook_id in source_data.notebooks or []:
                await source.add_to_notebook(notebook_id)

            try:
                command_id = await _submit_source_command(
                    source,
                    content_state,
                    source_data.notebooks,
                    transformation_ids,
                    source_data.embed,
                )
                logger.info(f"Submitted async processing command: {command_id}")

                return source_to_response(
                    source,
                    0,
                    include_asset=False,
                    command_id=command_id,
                    status="new",
                    processing_info={"async": True, "queued": True},
                )

            except Exception as e:
                logger.error(f"Failed to submit async processing command: {e}")
                try:
                    await source.delete()
                except Exception:
                    pass
                if file_path and upload_file:
                    try:
                        os.unlink(file_path)
                    except Exception:
                        pass
                raise HTTPException(status_code=500, detail=f"Failed to queue processing: {str(e)}")

        else:
            logger.info("Using sync processing path")

            try:
                import commands.source_commands  # noqa: F401

                source = Source(title=source_data.title or "Processing...", topics=[])
                await source.save()

                for notebook_id in source_data.notebooks or []:
                    await source.add_to_notebook(notebook_id)

                command_input = SourceProcessingInput(
                    source_id=str(source.id),
                    content_state=content_state,
                    notebook_ids=source_data.notebooks,
                    transformations=transformation_ids,
                    embed=source_data.embed,
                )

                result = await asyncio.to_thread(
                    execute_command_sync,
                    "open_notebook",
                    "process_source",
                    command_input.model_dump(),
                    timeout=300,
                )

                if not result.is_success():
                    logger.error(f"Sync processing failed: {result.error_message}")
                    try:
                        await source.delete()
                    except Exception:
                        pass
                    if file_path and upload_file:
                        try:
                            os.unlink(file_path)
                        except Exception:
                            pass
                    raise HTTPException(
                        status_code=500,
                        detail=f"Processing failed: {result.error_message}",
                    )

                if not source.id:
                    raise HTTPException(status_code=500, detail="Source ID is missing")
                processed_source = await Source.get(source.id)
                if not processed_source:
                    raise HTTPException(status_code=500, detail="Processed source not found")

                embedded_chunks = await processed_source.get_embedded_chunks()
                return source_to_response(processed_source, embedded_chunks)

            except Exception as e:
                logger.error(f"Sync processing failed: {e}")
                if file_path and upload_file:
                    try:
                        os.unlink(file_path)
                    except Exception:
                        pass
                raise

    except HTTPException:
        if file_path and upload_file:
            try:
                os.unlink(file_path)
            except Exception:
                pass
        raise
    except InvalidInputError as e:
        if file_path and upload_file:
            try:
                os.unlink(file_path)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating source: {str(e)}")
        if file_path and upload_file:
            try:
                os.unlink(file_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Error creating source: {str(e)}")


@router.post("/sources/json", response_model=SourceResponse)
async def create_source_json(source_data: SourceCreate):
    """Create a new source using JSON payload (legacy endpoint for backward compatibility)."""
    form_data = (source_data, None)
    return await create_source(form_data)


@router.post("/sources/{source_id}/retry", response_model=SourceResponse)
async def retry_source_processing(source_id: str):
    """Retry processing for a failed or stuck source."""
    try:
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        # Authoritative duplicate guard: any non-terminal process_source row for
        # this source, not just the one source.command happens to point at. Two
        # rapid Retry clicks otherwise queue two full re-parses of the same PDF,
        # and build_sections is delete-then-rebuild, so they race each other's
        # blocks. Checked before the status probe because it cannot throw.
        if await command_in_flight(source_id, "process_source"):
            raise HTTPException(
                status_code=409,
                detail="Source is already processing. Cannot retry while processing is active.",
            )

        if source.command:
            try:
                status = await source.get_status()
            except Exception as e:
                # A status probe failure must not block a retry — that is the one
                # case where a stuck source most needs one.
                logger.warning(f"Failed to check current status for source {source_id}: {e}")
            else:
                # Raised outside the try: an HTTPException in it would be caught
                # by the `except Exception` above and downgraded to a warning,
                # letting the duplicate submit through.
                if status in ["running", "queued"]:
                    raise HTTPException(
                        status_code=409,
                        detail="Source is already processing. Cannot retry while processing is active.",
                    )

        references = await repo_query(
            "SELECT VALUE out FROM reference WHERE in = $source_id",
            {"source_id": ensure_record_id(source.id or source_id)},
        )
        notebook_ids = [str(nb_id) for nb_id in references] if references else []

        if not notebook_ids:
            raise HTTPException(
                status_code=400, detail="Source is not associated with any notebooks"
            )

        content_state = {}
        if source.asset:
            if source.asset.file_path:
                content_state = {"file_path": source.asset.file_path, "delete_source": False}
            elif source.asset.url:
                content_state = {"url": source.asset.url}
            else:
                raise HTTPException(
                    status_code=400, detail="Source asset has no file_path or url"
                )
        else:
            if source.full_text:
                content_state = {"content": source.full_text}
            else:
                raise HTTPException(
                    status_code=400, detail="Cannot determine source content for retry"
                )

        try:
            command_id = await _submit_source_command(
                source,
                content_state,
                notebook_ids,
                [],
                True,
            )
            logger.info(f"Submitted retry processing command: {command_id} for source {source_id}")

            embedded_chunks = await source.get_embedded_chunks()
            return source_to_response(
                source,
                embedded_chunks,
                command_id=command_id,
                status="queued",
                processing_info={"retry": True, "queued": True},
            )

        except Exception as e:
            logger.error(f"Failed to submit retry processing command for source {source_id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to queue retry processing: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying source processing for {source_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error retrying source processing: {str(e)}"
        )


@router.post("/sources/{source_id}/verify-clean")
async def rerun_verify_clean(source_id: str):
    """Manually re-run the vision proofing pass over a source's sections.

    The ingest path chains this automatically, but a phase can end without
    finishing: every section's verify job can exhaust its retries, or a stale
    fan-out can be superseded mid-flight. Nothing observes those cases, so this
    is the deliberate re-trigger. Coalesced — a pending run wins and returns 409
    rather than stacking a second orchestrator row.

    Note this also restarts the SUMMARIZE phase when it completes: the last
    verify job chains ``summarize_source``.
    """
    await Source.get_meta(source_id)

    if await command_in_flight(source_id, "verify_clean_source"):
        raise HTTPException(
            status_code=409,
            detail="A verify-clean run is already queued for this source.",
        )

    command_id = await CommandService.submit_command_job(
        "open_notebook", "verify_clean_source", {"source_id": source_id}
    )
    logger.info(f"Submitted manual verify_clean_source {command_id} for {source_id}")
    return {"command_id": command_id}


@router.post("/sources/{source_id}/summarize")
async def rerun_summarize(source_id: str):
    """Manually re-run chapter summaries for a source, skipping the verify phase.

    Use when proofing is already done (or deliberately skipped) and only the
    summaries need rebuilding. Summaries read ``cleaned_content`` when verify has
    landed and fall back to the raw parse otherwise.
    """
    await Source.get_meta(source_id)

    if await command_in_flight(source_id, "summarize_source"):
        raise HTTPException(
            status_code=409,
            detail="A summarize run is already queued for this source.",
        )

    command_id = await CommandService.submit_command_job(
        "open_notebook", "summarize_source", {"source_id": source_id}
    )
    logger.info(f"Submitted manual summarize_source {command_id} for {source_id}")
    return {"command_id": command_id}


@router.post("/sources/{source_id}/reparse")
async def reparse_source(source_id: str):
    """Explicitly rebuild the block substrate for a source (Decision #8).

    Submits ``build_blocks`` with ``force=true`` — bypassing the content-hash
    gate — so the user can re-run the parser (e.g. after a parser upgrade). No
    auto-on-open: this is the deliberate trigger. Returns the queued command id
    and the generation the new parse will write. 409 while a parse is already
    building (its header is ``status='building'``) so we never race two builds
    into the same generation.
    """
    # Existence check without shipping the textbook-sized full_text/page_map.
    await Source.get_meta(source_id)

    sid = ensure_record_id(source_id)
    headers = await repo_query(
        "SELECT gen, status FROM source_parse WHERE source = $sid",
        {"sid": sid},
    )

    if any(h.get("status") == "building" for h in (headers or [])):
        raise HTTPException(
            status_code=409,
            detail="A parse is already building for this source. Wait for it to finish before re-parsing.",
        )

    max_gen = max((h.get("gen") or 0 for h in (headers or [])), default=0)
    gen_expected = max_gen + 1

    try:
        command_id = await CommandService.submit_command_job(
            "open_notebook",
            "build_blocks",
            {"source_id": str(sid), "force": True},
        )
    except Exception as e:
        logger.error(f"Failed to submit reparse command for source {source_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to queue re-parse: {str(e)}"
        )

    logger.info(
        f"Submitted reparse (build_blocks force) command {command_id} "
        f"for source {source_id} (gen_expected={gen_expected})"
    )
    return {"command_id": command_id, "gen_expected": gen_expected}
