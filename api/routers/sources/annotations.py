from typing import List, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.models import (
    AnnotationResponse,
    CreateAnnotationRequest,
    UpdateAnnotationRequest,
)
from open_notebook.domain.notebook import Source, SourceAnnotation
from open_notebook.exceptions import NotFoundError
from open_notebook.utils.block_anchor import resolve_anchor

router = APIRouter()


def _anchor_state(
    annotation: SourceAnnotation, parse_generation: Optional[int]
) -> str:
    """Derive annotation staleness (db-design §2.3 — never stored).

    No ``block_seq`` → ``legacy`` (rect/quote-only); anchored against a stale
    generation → ``stale``; otherwise ``anchored``."""
    if annotation.block_seq is None:
        return "legacy"
    if annotation.anchor_gen != parse_generation:
        return "stale"
    return "anchored"


def _annotation_to_response(
    annotation: SourceAnnotation, parse_generation: Optional[int]
) -> AnnotationResponse:
    return AnnotationResponse(
        id=annotation.id or "",
        source_id=str(annotation.source) if annotation.source else "",
        page=annotation.page,
        rect=annotation.rect,
        color=annotation.color,
        note=annotation.note,
        quote=annotation.quote,
        tags=annotation.tags,
        block_seq=annotation.block_seq,
        block_end_seq=annotation.block_end_seq,
        anchor_start=annotation.anchor_start,
        anchor_end=annotation.anchor_end,
        anchor_gen=annotation.anchor_gen,
        anchor_state=_anchor_state(annotation, parse_generation),
        created=str(annotation.created),
        updated=str(annotation.updated),
    )


@router.get("/sources/{source_id}/annotations", response_model=List[AnnotationResponse])
async def get_source_annotations(source_id: str):
    """List all PDF highlight annotations for a source, oldest first."""
    try:
        source = await Source.get_meta(source_id)

        annotations = await SourceAnnotation.get_for_source(source_id)
        return [
            _annotation_to_response(a, source.parse_generation) for a in annotations
        ]
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    except Exception as e:
        logger.error(f"Error fetching annotations for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching annotations: {str(e)}")


@router.post(
    "/sources/{source_id}/annotations",
    response_model=AnnotationResponse,
    status_code=201,
)
async def create_source_annotation(source_id: str, request: CreateAnnotationRequest):
    """Create a PDF highlight annotation for a source.

    The anchor (block range + char offsets) is server-resolved from the rect +
    quote against the current parse generation; an un-parsed source stores a
    legacy rect/quote-only annotation (db-design §2.3 / Track D1)."""
    try:
        source = await Source.get_meta(source_id)

        annotation = SourceAnnotation(
            source=source_id,
            page=request.page,
            rect=[r.model_dump() for r in request.rect],
            color=request.color,
            note=request.note,
            quote=request.quote,
            tags=request.tags,
        )

        anchor = await resolve_anchor(
            source, [r.model_dump() for r in request.rect], request.quote
        )
        if anchor is not None:
            annotation.block_seq = anchor.block_seq
            annotation.block_end_seq = anchor.block_end_seq
            annotation.anchor_start = anchor.anchor_start
            annotation.anchor_end = anchor.anchor_end
            annotation.anchor_gen = anchor.anchor_gen
            annotation.quote_hash = anchor.quote_hash

        await annotation.save()
        return _annotation_to_response(annotation, source.parse_generation)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    except Exception as e:
        logger.error(f"Error creating annotation for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating annotation: {str(e)}")


@router.patch("/annotations/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(annotation_id: str, request: UpdateAnnotationRequest):
    """Update an annotation's note, color and/or tags. Anchors are immutable."""
    try:
        annotation = await SourceAnnotation.get(annotation_id)

        if request.note is not None:
            annotation.note = request.note
        if request.color is not None:
            annotation.color = request.color
        if request.tags is not None:
            annotation.tags = request.tags

        await annotation.save()

        # Fetch the source's current generation only for the derived anchor_state.
        parse_generation: Optional[int] = None
        if annotation.source:
            try:
                source = await Source.get_meta(str(annotation.source))
                parse_generation = source.parse_generation
            except NotFoundError:
                parse_generation = None
        return _annotation_to_response(annotation, parse_generation)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Annotation not found")
    except Exception as e:
        logger.error(f"Error updating annotation {annotation_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating annotation: {str(e)}")


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str):
    """Delete an annotation."""
    try:
        annotation = await SourceAnnotation.get(annotation_id)
        await annotation.delete()

        return {"message": "Annotation deleted successfully"}
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Annotation not found")
    except Exception as e:
        logger.error(f"Error deleting annotation {annotation_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting annotation: {str(e)}")
