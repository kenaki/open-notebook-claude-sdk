import os
from typing import Literal, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from loguru import logger

from api.routers.chat.schemas import MediaItem
from api.upload_utils import resolve_within, save_uploaded_file
from open_notebook.config import CHAT_MEDIA_FOLDER

router = APIRouter()


def _classify_media(content_type: Optional[str]) -> Literal["image", "video"]:
    """Map an upload's MIME type to the MediaItem kind (image|video)."""
    ctype = (content_type or "").lower()
    if ctype.startswith("video/"):
        return "video"
    if ctype.startswith("image/"):
        return "image"
    raise HTTPException(
        status_code=400,
        detail="Unsupported media type: only image/* and video/* are accepted",
    )


@router.post("/chat/media", response_model=MediaItem)
async def upload_chat_media(file: UploadFile = File(...)):
    """Upload an image/video to attach to a chat message.

    Stored as a standalone file under ``data/uploads/chat-media/`` (no DB record in
    v1 — see coordinator Q-mediastore). Returns the MediaItem the composer attaches
    to the next ``POST /chat/execute`` call.
    """
    media_type = _classify_media(file.content_type)
    try:
        saved_path = await save_uploaded_file(file, CHAT_MEDIA_FOLDER)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error saving chat media: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error saving chat media: {str(e)}")

    filename = os.path.basename(saved_path)
    return MediaItem(
        type=media_type,
        url=f"/api/chat/media/{filename}",
        label=file.filename or filename,
        duration=None,
    )


@router.get("/chat/media/{filename}")
async def get_chat_media(filename: str):
    """Serve a previously uploaded chat-media file (path-traversal guarded)."""
    try:
        resolved_path = resolve_within(CHAT_MEDIA_FOLDER, filename)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access to file denied")

    if not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="Media not found")

    return FileResponse(
        path=resolved_path, filename=os.path.basename(resolved_path)
    )
