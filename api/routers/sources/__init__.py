from fastapi import APIRouter

from api.routers.sources.annotations import router as annotations_router
from api.routers.sources.blocks import router as blocks_router
from api.routers.sources.create import router as create_router
from api.routers.sources.crud import router as crud_router
from api.routers.sources.insights import router as insights_router
from api.routers.sources.sections import router as sections_router

router = APIRouter()
router.include_router(create_router)
router.include_router(crud_router)
router.include_router(insights_router)
router.include_router(sections_router)
router.include_router(annotations_router)
router.include_router(blocks_router)
