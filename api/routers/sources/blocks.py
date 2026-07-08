"""Block read endpoints + crop serving (pdf-block-ingestion Track C, chunk C1).

The hot-path reads of db-design §3 exposed as REST, payload-hygienic by
construction: existence is checked with ``Source.get_meta`` (never a full
``Source.get``), every DB touch goes through the ``domain/blocks.py`` helpers
(point-gets / prefix range scans, zero table scans), and optional projection
fields are dropped from the JSON via ``response_model_exclude_none``.

All block reads target the source's CURRENT parse generation
(``source.parse_generation``); un-parsed sources return a clean 404.
"""

import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from loguru import logger

from api.models import BlockResponse, PageBlocksResponse, ParseStatusResponse
from open_notebook.config import UPLOADS_FOLDER
from open_notebook.domain import blocks as block_helpers
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import NotFoundError

router = APIRouter()


def _src_key(source_id: str) -> str:
    """Bare record-id key from ``source:<key>`` (matches db-design §1 ``src_key``)."""
    s = str(source_id)
    return s.split(":", 1)[1] if ":" in s else s


async def _get_source_meta(source_id: str) -> Source:
    """Existence/metadata check via the OMIT-heavy ``get_meta`` (db-design §6.3)."""
    try:
        return await Source.get_meta(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")


def _require_current_gen(source: Source) -> int:
    """The current parse generation, or a 404 if the source was never parsed."""
    if source.parse_generation is None:
        raise HTTPException(status_code=404, detail="Source has not been parsed")
    return source.parse_generation


def _block_to_response(row: dict, source_id: str) -> BlockResponse:
    """Map a raw block projection dict to :class:`BlockResponse`.

    ``image_url`` is derived from ``image_ref`` (present only on text/full
    projections); overlay/window projections that omit a field leave it None so
    it is dropped from the serialized payload.
    """
    seq = row["seq"]
    image_ref = row.get("image_ref")
    image_url = f"/api/sources/{source_id}/blocks/{seq}/image" if image_ref else None
    return BlockResponse(
        seq=seq,
        type=row["type"],
        page=row.get("page"),
        bbox=row.get("bbox"),
        parent_seq=row.get("parent_seq"),
        level=row.get("level"),
        section_path=row.get("section_path"),
        text=row.get("text"),
        latex=row.get("latex"),
        image_url=image_url,
        table_data=row.get("table_data"),
    )


@router.get(
    "/sources/{source_id}/parse",
    response_model=ParseStatusResponse,
    response_model_exclude_none=True,
)
async def get_source_parse_status(source_id: str):
    """Parse status header for the source's current generation (db-design §2.2).

    404 if the source was never parsed. Kept to one point-get so the frontend
    can poll it cheaply.
    """
    try:
        source = await _get_source_meta(source_id)
        gen = _require_current_gen(source)
        header = await block_helpers.get_parse_header(_src_key(source.id), gen)
        if header is None:
            raise HTTPException(status_code=404, detail="Parse header not found")
        return ParseStatusResponse(
            parse_status=source.parse_status,
            gen=gen,
            parser_name=source.parser_name or header.parser_name,
            parser_version=source.parser_version or header.parser_version,
            block_count=header.block_count,
            page_count=header.page_count,
            section_index=header.section_index,
            error=header.error,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching parse status for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching parse status: {str(e)}")


@router.get(
    "/sources/{source_id}/blocks",
    response_model=PageBlocksResponse,
    response_model_exclude_none=True,
)
async def get_page_blocks(
    source_id: str,
    page: int = Query(..., ge=1, description="1-based physical page number"),
    include_text: bool = Query(
        False, description="Include text/latex/section_path (defaults to overlay only)"
    ),
):
    """One page's blocks in reading (seq) order (db-design §3a).

    Overlay projection by default (``seq,type,page,bbox,parent_seq,level``, no
    text); ``include_text=true`` adds text/latex/section_path/table_data and the
    derived ``image_url``.
    """
    try:
        source = await _get_source_meta(source_id)
        gen = _require_current_gen(source)
        src_key = _src_key(source.id)
        header = await block_helpers.get_parse_header(src_key, gen)
        if header is None or header.page_index is None:
            raise HTTPException(status_code=404, detail="Parse header not found")
        rows = await block_helpers.get_page_blocks(
            src_key, gen, page, header.page_index, include_text=include_text
        )
        return PageBlocksResponse(
            page=page,
            gen=gen,
            blocks=[_block_to_response(r, source_id) for r in rows],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching blocks for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching blocks: {str(e)}")


@router.get(
    "/sources/{source_id}/blocks/{seq}/window",
    response_model=list[BlockResponse],
    response_model_exclude_none=True,
)
async def get_block_window(
    source_id: str,
    seq: int,
    radius: int = Query(3, ge=0, le=50, description="Blocks on each side of seq"),
):
    """The ``[seq-radius .. seq+radius]`` window with text (db-design §3b).

    Returns up to ``radius*2+1`` blocks in seq order (fewer near seq 0 / the
    document end). An out-of-range seq simply yields an empty list.
    """
    try:
        source = await _get_source_meta(source_id)
        gen = _require_current_gen(source)
        rows = await block_helpers.get_window(_src_key(source.id), gen, seq, radius)
        return [_block_to_response(r, source_id) for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching block window for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching block window: {str(e)}")


@router.get("/sources/{source_id}/blocks/{seq}/image")
async def get_block_image(source_id: str, seq: int):
    """Serve a figure/table crop PNG (db-design §6, Decision #6).

    File lives at ``{UPLOADS_FOLDER}/blocks/{src_key}/{gen}/{seq}.png``; the
    resolved path is validated to stay under ``UPLOADS_FOLDER`` (mirrors
    ``_resolve_source_file``). 404 if the crop is missing.
    """
    try:
        source = await _get_source_meta(source_id)
        gen = _require_current_gen(source)
        resolved = _resolve_block_image(_src_key(source.id), gen, seq)
        return FileResponse(path=resolved, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving block image for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to serve block image")


@router.get(
    "/sources/{source_id}/blocks/{seq}",
    response_model=BlockResponse,
    response_model_exclude_none=True,
)
async def get_block(source_id: str, seq: int):
    """One full block including ``table_data`` (point-get, db-design §3)."""
    try:
        source = await _get_source_meta(source_id)
        gen = _require_current_gen(source)
        block = await block_helpers.get_block(_src_key(source.id), gen, seq)
        if block is None:
            raise HTTPException(status_code=404, detail="Block not found")
        return _block_to_response(block.model_dump(), source_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching block for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching block: {str(e)}")


def _resolve_block_image(src_key: str, gen: int, seq: int) -> str:
    """Resolve + path-validate a crop PNG under ``UPLOADS_FOLDER``; raise 403 on
    escape, 404 if absent (mirrors ``crud._resolve_source_file`` guarding)."""
    safe_root = os.path.realpath(UPLOADS_FOLDER)
    candidate = os.path.join(
        UPLOADS_FOLDER, "blocks", src_key, str(gen), f"{seq}.png"
    )
    resolved = os.path.realpath(candidate)
    if resolved != safe_root and not resolved.startswith(safe_root + os.sep):
        logger.warning(f"Blocked block-image access outside uploads dir: {candidate}")
        raise HTTPException(status_code=403, detail="Access to file denied")
    if not os.path.exists(resolved):
        raise HTTPException(status_code=404, detail="Block image not found")
    return resolved
