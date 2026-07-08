from fastapi import APIRouter, HTTPException
from loguru import logger

from api.context_service import build_context_data
from api.models import ContextRequest, ContextResponse
from open_notebook.domain.notebook import Notebook
from open_notebook.exceptions import InvalidInputError
from open_notebook.utils import token_count

router = APIRouter()


@router.post("/notebooks/{notebook_id}/context", response_model=ContextResponse)
async def get_notebook_context(notebook_id: str, context_request: ContextRequest):
    """Get context for a notebook based on configuration."""
    try:
        # Verify notebook exists
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        # A provided ContextConfig (even empty) selects the config path; its
        # absence selects the default all-sources path — matching the original
        # `if context_request.context_config:` truthiness check.
        cfg = context_request.context_config
        context_config = {"sources": cfg.sources, "notes": cfg.notes} if cfg else None

        sources_ctx, notes_ctx, total_content = await build_context_data(
            notebook, context_config
        )

        # Calculate estimated token count
        estimated_tokens = token_count(total_content) if total_content else 0

        return ContextResponse(
            notebook_id=notebook_id,
            sources=sources_ctx,
            notes=notes_ctx,
            total_tokens=estimated_tokens,
        )

    except HTTPException:
        raise
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting context for notebook {notebook_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting context: {str(e)}")
