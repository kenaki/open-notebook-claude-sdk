from typing import List

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.models import (
    AnnotationResponse,
    CreateAnnotationRequest,
    UpdateAnnotationRequest,
)
from open_notebook.domain.notebook import Source, SourceAnnotation
from open_notebook.exceptions import NotFoundError

router = APIRouter()


def _annotation_to_response(annotation: SourceAnnotation) -> AnnotationResponse:
    return AnnotationResponse(
        id=annotation.id or "",
        source_id=str(annotation.source) if annotation.source else "",
        page=annotation.page,
        rect=annotation.rect,
        color=annotation.color,
        note=annotation.note,
        quote=annotation.quote,
        tags=annotation.tags,
        created=str(annotation.created),
        updated=str(annotation.updated),
    )


@router.get("/sources/{source_id}/annotations", response_model=List[AnnotationResponse])
async def get_source_annotations(source_id: str):
    """List all PDF highlight annotations for a source, oldest first."""
    try:
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        annotations = await SourceAnnotation.get_for_source(source_id)
        return [_annotation_to_response(a) for a in annotations]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching annotations for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching annotations: {str(e)}")


@router.post(
    "/sources/{source_id}/annotations",
    response_model=AnnotationResponse,
    status_code=201,
)
async def create_source_annotation(source_id: str, request: CreateAnnotationRequest):
    """Create a PDF highlight annotation for a source."""
    try:
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        annotation = SourceAnnotation(
            source=source_id,
            page=request.page,
            rect=[r.model_dump() for r in request.rect],
            color=request.color,
            note=request.note,
            quote=request.quote,
            tags=request.tags,
        )
        await annotation.save()
        return _annotation_to_response(annotation)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating annotation for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating annotation: {str(e)}")


@router.patch("/annotations/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(annotation_id: str, request: UpdateAnnotationRequest):
    """Update an annotation's note, color and/or tags."""
    try:
        annotation = await SourceAnnotation.get(annotation_id)

        if request.note is not None:
            annotation.note = request.note
        if request.color is not None:
            annotation.color = request.color
        if request.tags is not None:
            annotation.tags = request.tags

        await annotation.save()
        return _annotation_to_response(annotation)
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
