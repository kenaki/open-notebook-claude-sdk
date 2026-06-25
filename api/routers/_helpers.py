from typing import Any, Dict, Optional, Type, TypeVar

from fastapi import HTTPException

from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import NotFoundError

T = TypeVar("T", bound=ObjectModel)


def ensure_prefix(id: str, table: str) -> str:
    prefix = f"{table}:"
    return id if id.startswith(prefix) else f"{prefix}{id}"


async def get_or_404(
    model_cls: Type[T],
    id: str,
    name: str,
    *,
    prefix: Optional[str] = None,
) -> T:
    if prefix:
        id = ensure_prefix(id, prefix)
    try:
        return await model_cls.get(id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"{name} not found")


def session_to_response(
    session: Any,
    *,
    notebook_id: Optional[str],
    message_count: Optional[int],
    default_title: str,
) -> Dict[str, Any]:
    """Build the dict payload for ChatSessionResponse / SourceChatSessionResponse.

    Pass default_title="" on create (no fallback label) or "Untitled Session"
    on read/update (user-visible label required).
    """
    return {
        "id": session.id or "",
        "title": session.title or default_title,
        "notebook_id": notebook_id,
        "created": str(session.created),
        "updated": str(session.updated),
        "message_count": message_count,
        "model_override": getattr(session, "model_override", None),
        "parent_session_id": getattr(session, "parent_session_id", None),
        "quote": getattr(session, "quote", None),
        "tags": getattr(session, "tags", None) or [],
    }


def episode_to_response(
    episode: Any,
    *,
    job_status: Optional[str],
    error_message: Optional[str],
    audio_url: Optional[str],
) -> Dict[str, Any]:
    """Build the dict payload for PodcastEpisodeResponse."""
    return {
        "id": str(episode.id),
        "name": episode.name,
        "episode_profile": episode.episode_profile,
        "speaker_profile": episode.speaker_profile,
        "briefing": episode.briefing,
        "audio_file": episode.audio_file,
        "audio_url": audio_url,
        "transcript": episode.transcript,
        "outline": episode.outline,
        "created": str(episode.created) if episode.created else None,
        "job_status": job_status,
        "error_message": error_message,
    }
