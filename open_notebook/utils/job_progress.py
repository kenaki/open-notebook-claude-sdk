from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

# Cap on progress.events[] — oldest entries are trimmed (see append_job_event).
_MAX_EVENTS = 200


async def append_job_event(
    job_id: Optional[str],
    event_type: str,
    *,
    phase: Optional[str] = None,
    **payload: Any,
) -> None:
    """Append one entry to the ``command`` row's ``progress.events[]`` log
    (append-only, capped at ``_MAX_EVENTS``, oldest trimmed first) via a
    single raw SurrealQL ``UPDATE ... SET`` statement.

    ``repo_update``'s ``MERGE`` replaces the whole ``progress`` object, which
    would clobber ``events[]`` on every call — this writes directly into the
    nested path instead, so concurrent/rapid progress writes never race each
    other out.

    When ``phase`` is given, also stamps ``progress.phase`` (back-compat with
    existing tray/label consumers). When ``tool_name``/``tool_input`` are
    present in ``payload``, they're additionally stamped onto
    ``progress.tool_name``/``progress.tool_input`` (back-compat live label).

    Best-effort: a missing job_id or any DB error is swallowed — progress
    reporting must never break the calling pipeline.
    """
    if not job_id:
        return
    try:
        from open_notebook.database.repository import ensure_record_id, repo_query

        event: Dict[str, Any] = {
            "t": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            **payload,
        }

        # array::concat (not `+`) — this SurrealDB build rejects `array + array`;
        # negative-start array::slice IS supported (verified live against the
        # dev DB): slice keeps the newest (_MAX_EVENTS - 1) existing entries,
        # concat appends the new one, capping the log at _MAX_EVENTS.
        set_clauses = [
            "progress.events = array::concat("
            f"array::slice(progress.events ?? [], -{_MAX_EVENTS - 1}), [$event])"
        ]
        query_vars: Dict[str, Any] = {
            "id": ensure_record_id(job_id),
            "event": event,
        }

        if phase is not None:
            set_clauses.append("progress.phase = $phase")
            query_vars["phase"] = phase
        if "tool_name" in payload:
            set_clauses.append("progress.tool_name = $tool_name")
            query_vars["tool_name"] = payload["tool_name"]
        if "tool_input" in payload:
            set_clauses.append("progress.tool_input = $tool_input")
            query_vars["tool_input"] = payload["tool_input"]

        query = f"UPDATE $id SET {', '.join(set_clauses)};"
        await repo_query(query, query_vars)
    except Exception as exc:
        logger.debug(
            f"job event append skipped (type={event_type!r}, phase={phase!r}): {exc!r}"
        )


async def report_job_progress(job_id: Optional[str], phase: str, **extra: Any) -> None:
    """Stamp a human-readable phase (plus optional structured extras) onto the
    running ``command`` row so the background-jobs tray — and any UI reading
    the same job, e.g. the chat message list — can show live status.

    Delegates to :func:`append_job_event` (a ``"phase"`` event carrying
    ``label=phase`` plus any extras) so every progress mutation goes through
    the same race-free single-statement path. Signature and best-effort/
    swallow-errors behavior are unchanged — existing callers keep working.
    """
    await append_job_event(job_id, "phase", phase=phase, label=phase, **extra)
