from fastapi import APIRouter

from api.routers.chat.execute import router as execute_router
from api.routers.chat.media import router as media_router
from api.routers.chat.sessions import router as sessions_router

router = APIRouter()
router.include_router(sessions_router)
router.include_router(execute_router)
router.include_router(media_router)
