"""Boot-time reaping of orphaned ``running`` command rows.

surreal-commands only ever dispatches a command whose status is exactly ``new``:
the boot sweep (``SELECT * FROM command WHERE status = 'new'``) and the
live-query listener (``if "status" not in cmd or cmd["status"] == "new"``) both
filter on it. A worker that claims a command flips it to ``running`` and writes a
terminal status when the coroutine returns — but it installs no signal handler,
so a SIGTERM mid-job (``systemctl restart on-worker``) freezes the row at
``running`` forever. No later worker re-dispatches it, and ``_job_guards`` counts
any non-terminal row as "upstream still in flight", so one frozen row wedges that
source's entire fan-out permanently.

A freshly-started worker process cannot own a row that was already ``running``
before it booted, so on boot every such row is orphaned by definition.

Orphans are failed rather than requeued to ``new`` on purpose. A requeue restarts
the job from scratch on every worker boot, so a long parse that never fits
between two restarts loops forever, re-doing the same work and never landing.
Failing surfaces the state in the UI and leaves the retry decision to the user.

This assumes a single worker process, which is how the ``on-worker`` unit runs.
A second concurrent worker would have its in-flight rows failed out from under
it; set ``ON_WORKER_REAP_ORPHANS=0`` in that case.
"""

import os
from typing import Any, Dict, List

from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query

# Terminal statuses a reaped row is moved to, and the marker written to
# error_message so a reaped row is distinguishable from a genuine job failure.
REAP_ERROR_MESSAGE = (
    "Worker restarted while this job was running. A 'running' row is never "
    "re-dispatched, so the job was failed on worker boot. Re-run it."
)


def reaping_enabled() -> bool:
    """False only when explicitly disabled (multi-worker deployments)."""
    return os.getenv("ON_WORKER_REAP_ORPHANS", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    )


async def reap_orphaned_commands() -> List[Dict[str, Any]]:
    """Fail every ``running`` command row and return the rows that were reaped.

    Must run before the worker starts dispatching, and only ever from the worker
    process itself — see the module docstring.
    """
    if not reaping_enabled():
        logger.info("Orphan reaper disabled via ON_WORKER_REAP_ORPHANS")
        return []

    try:
        reaped = (
            await repo_query(
                "UPDATE command SET status = 'failed', error_message = $msg "
                "WHERE status = 'running' RETURN AFTER;",
                {"msg": REAP_ERROR_MESSAGE},
            )
            or []
        )
    except Exception as e:
        # A reaper failure must never stop the worker from coming up; the
        # orphans stay stuck, which is exactly the status quo without it.
        logger.error(f"Orphan reaper failed, starting worker anyway: {e}")
        return []

    if not reaped:
        logger.info("Orphan reaper: no stuck 'running' commands")
        return []

    for row in reaped:
        logger.warning(
            f"Orphan reaper: failed stuck command {row.get('id')} "
            f"({row.get('name')}) left 'running' by a previous worker"
        )

    await _settle_parse_status_for(reaped)
    logger.info(f"Orphan reaper: reaped {len(reaped)} orphaned command(s)")
    return reaped


async def _settle_parse_status_for(reaped: List[Dict[str, Any]]) -> None:
    """Move sources off a transient ``parse_status`` after their job was reaped.

    Otherwise the command row reads ``failed`` while the source still reads
    ``pending``, and the reader renders a processing spinner over a pipeline
    nothing is driving.

    The command dying does not mean the *parse* died. ``build_blocks`` finalizes
    the ``source_parse`` header to ``ready`` as its last step, so a source can
    hold a complete block substrate while ``process_source`` was killed before it
    stamped the source row. The header is the authority on whether the parse
    landed: ``ready`` there settles to ``ready``, anything else to ``failed``.
    Trusting the command row instead would mark finished parses as failed and
    push the user into a needless multi-hour re-parse.
    """
    source_ids = {
        sid for row in reaped if (sid := (row.get("args") or {}).get("source_id"))
    }
    for source_id in source_ids:
        try:
            settled = "failed"
            header = await repo_query(
                # `generation` must appear in the projection for `ORDER BY
                # generation` to parse ("Missing order idiom") — same SurrealQL
                # quirk as the section query in embedding_commands.py.
                "SELECT status, generation FROM source_parse WHERE source = $sid "
                "ORDER BY generation DESC LIMIT 1;",
                {"sid": ensure_record_id(source_id)},
            )
            if header and header[0].get("status") == "ready":
                settled = "ready"

            await repo_query(
                "UPDATE $sid SET parse_status = $settled "
                "WHERE parse_status IN ['pending', 'parsing', 'embedding'];",
                {"sid": ensure_record_id(source_id), "settled": settled},
            )
            logger.info(
                f"Orphan reaper: settled parse_status='{settled}' for {source_id}"
            )
        except Exception as e:
            logger.warning(f"Orphan reaper: parse_status stamp skipped for {source_id}: {e}")
