from typing import Any, Optional

from loguru import logger


async def report_job_progress(job_id: Optional[str], phase: str, **extra: Any) -> None:
    """Stamp a human-readable phase (plus optional structured extras) onto the
    running ``command`` row so the background-jobs tray — and any UI reading
    the same job, e.g. the chat message list — can show live status.

    Best-effort: a missing job_id or any DB error is swallowed — progress
    reporting must never break the calling pipeline.
    """
    if not job_id:
        return
    try:
        from open_notebook.database.repository import repo_update

        await repo_update("command", job_id, {"progress": {"phase": phase, **extra}})
    except Exception as exc:
        logger.debug(f"progress report skipped (phase={phase!r}): {exc!r}")
