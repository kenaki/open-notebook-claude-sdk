from fastapi import APIRouter

from api.routers.sources.create import router as create_router
from api.routers.sources.crud import router as crud_router
from api.routers.sources.insights import router as insights_router

router = APIRouter()
router.include_router(create_router)
router.include_router(crud_router)
router.include_router(insights_router)
