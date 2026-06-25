from typing import List

from fastapi import APIRouter, HTTPException
from loguru import logger
from surreal_commands import submit_command

from api.models import CreateSourceInsightRequest, InsightCreationResponse, SourceInsightResponse
from open_notebook.domain.notebook import Source
from open_notebook.domain.transformation import Transformation

router = APIRouter()


@router.get("/sources/{source_id}/insights", response_model=List[SourceInsightResponse])
async def get_source_insights(source_id: str):
    """Get all insights for a specific source."""
    try:
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        insights = await source.get_insights()
        return [
            SourceInsightResponse(
                id=insight.id or "",
                source_id=source_id,
                insight_type=insight.insight_type,
                content=insight.content,
                created=str(insight.created),
                updated=str(insight.updated),
            )
            for insight in insights
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching insights for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching insights: {str(e)}")


@router.post(
    "/sources/{source_id}/insights",
    response_model=InsightCreationResponse,
    status_code=202,
)
async def create_source_insight(source_id: str, request: CreateSourceInsightRequest):
    """Start insight generation for a source by running a transformation.

    Returns immediately with 202 Accepted. Poll GET /sources/{source_id}/insights
    to see when the insight is ready.
    """
    try:
        source = await Source.get(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        transformation = await Transformation.get(request.transformation_id)
        if not transformation:
            raise HTTPException(status_code=404, detail="Transformation not found")

        command_id = submit_command(
            "open_notebook",
            "run_transformation",
            {
                "source_id": source_id,
                "transformation_id": request.transformation_id,
            },
        )
        logger.info(f"Submitted run_transformation command {command_id} for source {source_id}")

        return InsightCreationResponse(
            status="pending",
            message="Insight generation started",
            source_id=source_id,
            transformation_id=request.transformation_id,
            command_id=str(command_id),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting insight generation for source {source_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error starting insight generation: {str(e)}")
