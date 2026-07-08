import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from loguru import logger

from api.models import AssetModel, SourceListResponse, SourceStatusResponse, SourceUpdate
from api.routers.sources._helpers import source_to_response
from api.upload_utils import resolve_upload_file
from open_notebook.config import UPLOADS_FOLDER
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Notebook, Source
from open_notebook.exceptions import InvalidInputError, NotFoundError

router = APIRouter()


def _is_source_file_available(source: Source) -> Optional[bool]:
    if not source or not source.asset or not source.asset.file_path:
        return None

    safe_root = os.path.realpath(UPLOADS_FOLDER)
    resolved_path = os.path.realpath(source.asset.file_path)

    if not resolved_path.startswith(safe_root):
        return False

    return os.path.exists(resolved_path)


async def _resolve_source_file(source_id: str) -> tuple[str, str]:
    source = await Source.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    file_path = source.asset.file_path if source.asset else None
    if not file_path:
        raise HTTPException(status_code=404, detail="Source has no file to download")

    try:
        return resolve_upload_file(file_path)
    except PermissionError:
        logger.warning(f"Blocked download outside uploads directory for source {source_id}")
        raise HTTPException(status_code=403, detail="Access to file denied")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found on server")


@router.get("/sources", response_model=List[SourceListResponse])
async def get_sources(
    notebook_id: Optional[str] = Query(None, description="Filter by notebook ID"),
    limit: int = Query(50, ge=1, le=100, description="Number of sources to return (1-100)"),
    offset: int = Query(0, ge=0, description="Number of sources to skip"),
    sort_by: str = Query("updated", description="Field to sort by (created or updated)"),
    sort_order: str = Query("desc", description="Sort order (asc or desc)"),
):
    """Get sources with pagination and sorting support."""
    try:
        if sort_by not in ["created", "updated"]:
            raise HTTPException(status_code=400, detail="sort_by must be 'created' or 'updated'")
        if sort_order.lower() not in ["asc", "desc"]:
            raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

        order_clause = f"ORDER BY {sort_by} {sort_order.upper()}"

        if notebook_id:
            notebook = await Notebook.get(notebook_id)
            if not notebook:
                raise HTTPException(status_code=404, detail="Notebook not found")

            query = f"""
                SELECT id, asset, created, title, updated, topics, command,
                (SELECT VALUE count() FROM source_insight WHERE source = $parent.id GROUP ALL)[0].count OR 0 AS insights_count,
                (SELECT VALUE id FROM source_embedding WHERE source = $parent.id LIMIT 1) != [] AS embedded
                FROM (select value in from reference where out=$notebook_id)
                {order_clause}
                LIMIT $limit START $offset
                FETCH command
            """
            result = await repo_query(
                query,
                {
                    "notebook_id": ensure_record_id(notebook_id),
                    "limit": limit,
                    "offset": offset,
                },
            )
        else:
            query = f"""
                SELECT id, asset, created, title, updated, topics, command,
                (SELECT VALUE count() FROM source_insight WHERE source = $parent.id GROUP ALL)[0].count OR 0 AS insights_count,
                (SELECT VALUE id FROM source_embedding WHERE source = $parent.id LIMIT 1) != [] AS embedded
                FROM source
                {order_clause}
                LIMIT $limit START $offset
                FETCH command
            """
            result = await repo_query(query, {"limit": limit, "offset": offset})

        response_list = []
        for row in result:
            command = row.get("command")
            command_id = None
            status = None
            processing_info = None

            if command and isinstance(command, dict):
                command_id = str(command.get("id")) if command.get("id") else None
                status = command.get("status")
                result_data = command.get("result")
                execution_metadata = (
                    result_data.get("execution_metadata", {})
                    if isinstance(result_data, dict)
                    else {}
                )
                processing_info = {
                    "started_at": execution_metadata.get("started_at"),
                    "completed_at": execution_metadata.get("completed_at"),
                    "error": command.get("error_message"),
                }
            elif command:
                command_id = str(command)
                status = "unknown"

            response_list.append(
                SourceListResponse(
                    id=row["id"],
                    title=row.get("title"),
                    topics=row.get("topics") or [],
                    asset=AssetModel(
                        file_path=row["asset"].get("file_path") if row.get("asset") else None,
                        url=row["asset"].get("url") if row.get("asset") else None,
                    )
                    if row.get("asset")
                    else None,
                    embedded=row.get("embedded", False),
                    embedded_chunks=0,
                    insights_count=row.get("insights_count", 0),
                    created=str(row["created"]),
                    updated=str(row["updated"]),
                    command_id=command_id,
                    status=status,
                    processing_info=processing_info,
                )
            )

        return response_list
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching sources: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching sources: {str(e)}")


@router.get("/sources/{source_id}", response_model=None)
async def get_source(source_id: str):
    """Get a specific source by ID."""
    try:
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        status = None
        processing_info = None
        if source.command:
            try:
                status = await source.get_status()
                processing_info = await source.get_processing_progress()
            except Exception as e:
                logger.warning(f"Failed to get status for source {source_id}: {e}")
                status = "unknown"

        embedded_chunks = await source.get_embedded_chunks()

        notebooks_query = await repo_query(
            "SELECT VALUE out FROM reference WHERE in = $source_id",
            {"source_id": ensure_record_id(source.id or source_id)},
        )
        notebook_ids = [str(nb_id) for nb_id in notebooks_query] if notebooks_query else []

        # Cheap count query — avoids loading the full section tree for every GET /sources/{id}
        sections_count_result = await repo_query(
            "SELECT count() AS cnt FROM source_section WHERE source = $sid GROUP ALL",
            {"sid": ensure_record_id(source.id or source_id)},
        )
        sections_count = sections_count_result[0]["cnt"] if sections_count_result else 0

        return source_to_response(
            source,
            embedded_chunks,
            command_id=str(source.command) if source.command else None,
            status=status,
            processing_info=processing_info,
            file_available=_is_source_file_available(source),
            notebooks=notebook_ids,
            has_sections=sections_count > 0,
            sections_count=sections_count,
        )
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    except Exception as e:
        logger.error(f"Error fetching source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching source: {str(e)}")


@router.head("/sources/{source_id}/download")
async def check_source_file(source_id: str):
    """Check if a source has a downloadable file."""
    try:
        await _resolve_source_file(source_id)
        return Response(status_code=200)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking file for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to verify file")


@router.get("/sources/{source_id}/download")
async def download_source_file(source_id: str):
    """Download the original file associated with an uploaded source."""
    try:
        resolved_path, filename = await _resolve_source_file(source_id)
        return FileResponse(
            path=resolved_path,
            filename=filename,
            media_type="application/octet-stream",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading file for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to download source file")


@router.get("/sources/{source_id}/full-text")
async def get_source_full_text(source_id: str):
    """Return only the source's full_text (regenerated whole-book markdown).

    Kept off the GET /sources/{id} payload (E3) — the content tab fetches this
    lazily only when a source has no chapter sections. Targeted SELECT so we
    never load asset/embeddings/status just to read the text.
    """
    try:
        rows = await repo_query(
            "SELECT full_text FROM $sid",
            {"sid": ensure_record_id(source_id)},
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Source not found")
        return {"full_text": rows[0].get("full_text")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching full_text for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching source full text")


async def _failed_pipeline_jobs(source_id: str, command_id: Optional[str]) -> List[dict]:
    """Aggregate FAILED downstream pipeline jobs for a source.

    Every fan-out command (build_blocks, build_sections, verify_*, summarize_*,
    embed_source, generate_source_abstract) carries `args.source_id`, so a
    "process_source completed but 21 chapter summaries died" situation is
    visible instead of silently absent. Scoped to jobs created at/after the
    source's current processing command, so failures from an older, retried run
    don't haunt the status forever. Best-effort: returns [] on any error.
    """
    try:
        since_clause = ""
        vars: dict = {"sid": str(source_id)}
        if command_id:
            cmd_rows = await repo_query(
                "SELECT created FROM $cid", {"cid": ensure_record_id(command_id)}
            )
            if cmd_rows and cmd_rows[0].get("created"):
                since_clause = "AND created >= $since "
                vars["since"] = cmd_rows[0]["created"]

        rows = await repo_query(
            "SELECT name, error_message, updated FROM command "
            "WHERE args.source_id = $sid AND status = 'failed' "
            f"{since_clause}"
            "ORDER BY updated DESC LIMIT 200",
            vars,
        )
        by_name: dict = {}
        for row in rows or []:
            name = row.get("name") or "unknown"
            entry = by_name.setdefault(
                name, {"name": name, "count": 0, "latest_error": None}
            )
            entry["count"] += 1
            if entry["latest_error"] is None and row.get("error_message"):
                entry["latest_error"] = row["error_message"]
        return list(by_name.values())
    except Exception as e:
        logger.warning(f"Failed to aggregate failed jobs for {source_id}: {e}")
        return []


@router.get("/sources/{source_id}/status", response_model=SourceStatusResponse)
async def get_source_status(source_id: str):
    """Get processing status for a source, including downstream pipeline health."""
    try:
        source = await Source.get_meta(source_id)

        if not source.command:
            return SourceStatusResponse(
                status=None,
                message="Legacy source (completed before async processing)",
                processing_info=None,
                command_id=None,
                parse_status=source.parse_status,
            )

        try:
            status = await source.get_status()
            processing_info = await source.get_processing_progress()

            status_messages = {
                "completed": "Source processing completed successfully",
                "failed": "Source processing failed",
                "running": "Source processing in progress",
                "queued": "Source processing queued",
                "canceled": "Source processing canceled",
                "unknown": "Source processing status unknown",
            }
            message = status_messages.get(status or "", f"Source processing status: {status}")

            # Surface the specific failure reason directly in the message when
            # we have one — "Source processing failed" alone tells the user
            # nothing actionable.
            if status == "failed" and processing_info and processing_info.get("error"):
                message = str(processing_info["error"])

            failed_jobs = await _failed_pipeline_jobs(
                source_id, str(source.command) if source.command else None
            )

            return SourceStatusResponse(
                status=status,
                message=message,
                processing_info=processing_info,
                command_id=str(source.command) if source.command else None,
                parse_status=source.parse_status,
                failed_jobs=failed_jobs or None,
            )

        except Exception as e:
            logger.warning(f"Failed to get status for source {source_id}: {e}")
            return SourceStatusResponse(
                status="unknown",
                message="Failed to retrieve processing status",
                processing_info=None,
                command_id=str(source.command) if source.command else None,
                parse_status=source.parse_status,
            )

    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching status for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching source status: {str(e)}")


@router.post("/sources/{source_id}/cancel-processing")
async def cancel_source_processing(source_id: str):
    """Cancel all pending pipeline jobs for a source.

    Flips every queued/orphaned-running command that references this source to
    `canceled` so the worker never (re)processes them, and marks the source's
    parse lifecycle failed so the UI reflects the abort instead of a stuck
    'processing' state. An actively-executing job cannot be interrupted.
    """
    from api.command_service import CommandService

    try:
        await Source.get_meta(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")

    try:
        canceled = await CommandService.cancel_source_jobs(source_id)
        if canceled:
            try:
                await repo_query(
                    "UPDATE $sid SET parse_status = 'failed' "
                    "WHERE parse_status IN ['pending', 'parsing', 'embedding'];",
                    {"sid": ensure_record_id(source_id)},
                )
            except Exception as e:
                logger.warning(f"parse_status stamp after cancel skipped: {e}")
        return {"source_id": source_id, "canceled_jobs": canceled}
    except Exception as e:
        logger.error(f"Error canceling processing for source {source_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to cancel processing: {str(e)}"
        )


@router.put("/sources/{source_id}", response_model=None)
async def update_source(source_id: str, source_update: SourceUpdate):
    """Update a source."""
    try:
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        if source_update.title is not None:
            source.title = source_update.title
        if source_update.topics is not None:
            source.topics = source_update.topics

        await source.save()

        embedded_chunks = await source.get_embedded_chunks()
        return source_to_response(source, embedded_chunks)
    except HTTPException:
        raise
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating source: {str(e)}")


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str):
    """Delete a source."""
    try:
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        await source.delete()

        return {"message": "Source deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting source: {str(e)}")
