"""Ordering guards and submit-coalescing for the source fan-out pipeline.

The PDF ingest pipeline is a chain of fire-and-forget jobs:

    process_source -> build_blocks -> build_sections -> {verify_clean_source,
                                                         summarize_source}

``build_sections`` is delete-then-rebuild: every run deletes the source's
``source_section`` rows and mints fresh ids. Any fan-out that captured section
ids *before* a rebuild is therefore holding dead ids. ``build_blocks``
regenerates ``full_text`` and resubmits ``build_sections``, so a fan-out that
runs before blocks land is guaranteed to be orphaned.

Two primitives close that race:

- ``*_in_flight`` — "is an upstream job for this source still pending?" Command
  rows carry no timestamps, so "any non-terminal row for this source" is the
  whole predicate.
- ``submit_command_once`` — collapse a resubmit onto an already-pending job of
  the same name. Without it, each rebuild stacks another orchestrator row, and
  because the in-flight predicate has no way to age rows out, a single stuck row
  wedges every downstream fan-out permanently.
"""

from typing import Optional

from loguru import logger
from surreal_commands import submit_command

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.exceptions import ConfigurationError, NotFoundError


async def section_is_gone(section_id: str) -> bool:
    """True only when ``section_id`` genuinely has no row.

    ``ObjectModel.get`` funnels *every* exception into ``NotFoundError``
    (open_notebook/domain/base.py), so a transient DB error is indistinguishable
    from a deleted record at the call site. Treating both as "obsolete, skip"
    would silently drop real work on a database hiccup. Re-ask with a plain
    existence query: an empty result means truly deleted, while a raise here is a
    live DB problem and propagates so the job retries.
    """
    rows = await repo_query("SELECT id FROM $id", {"id": ensure_record_id(section_id)})
    return not rows


async def command_in_flight(source_id: str, name: str) -> bool:
    """True while a job named ``name`` for this source is queued or running."""
    rows = await repo_query(
        "SELECT count() AS n FROM command "
        "WHERE name = $name AND args.source_id = $sid "
        "AND status IN ['new', 'running'] GROUP ALL",
        {"sid": source_id, "name": name},
    )
    return bool(rows and rows[0].get("n", 0) > 0)


async def chaptering_in_flight(source_id: str) -> bool:
    """True while ``build_sections`` for this source is queued or running.

    Sampling the tree mid-build sees a PARTIAL tree, not an empty one — observed
    live on the Hands-on-ML book: ``verify_clean_source`` ran 6s into a 54s
    rebuild and fanned out over 117 of the eventual 472 sections. An empty-tree
    check alone cannot close that race.
    """
    return await command_in_flight(source_id, "build_sections")


async def blocks_in_flight(source_id: str) -> bool:
    """True while ``build_blocks`` for this source is queued or running.

    Waiting only on ``build_sections`` misses this window: the block job has not
    queued its rebuild yet, so the chaptering guard reads clear and the fan-out
    proceeds over a generation that is about to be deleted.

    Orchestrators DEFER rather than raise-to-retry on this one — ``build_blocks``
    can run for minutes on a large PDF and would exhaust the retry budget.
    ``build_sections`` resubmits them once the final tree exists.
    """
    return await command_in_flight(source_id, "build_blocks")


# A job that loses the heavy slot is BLOCKED, not BROKEN. The local Ollama slot
# holds one model at a time, and swapping a 35B model takes minutes, so a job
# that arrives mid-swap gets a gate 503. Raising there consumed one of the
# command's bounded retry attempts (summarize_section had a 15s budget total),
# and once the budget ran out the job was marked `failed` — indistinguishable in
# the tray from a genuine error. Callers requeue on these instead.
#
# Matched on the message, NOT via classify_error: that helper defaults every
# UNCLASSIFIED exception to ExternalServiceError, so keying off its return would
# quietly reclassify real bugs (AttributeError, KeyError, …) as "waiting for a
# model" and requeue them until the cap — burying the error we most want to see.
# This list is an allowlist and the default answer is "no, that's a real error".
_BUSY_MARKERS = (
    "503",
    "service unavailable",
    "overloaded",
    "server busy",
    "429",
    "rate limit",
    "too many requests",
    "model is loading",
    "loading model",
)

# Backstop against a requeue loop that never converges (e.g. the model is gone,
# not merely busy). Past this many requeues the job fails for real.
MAX_REQUEUES = 25


def is_resource_busy(exc: BaseException) -> bool:
    """True only when ``exc`` says the heavy slot is busy, not that the job broke.

    Permanent classes short-circuit to False even if their text happens to
    contain a marker — a ValueError is a bug in the job, never a busy resource.
    """
    if isinstance(exc, (ValueError, ConfigurationError, NotFoundError)):
        return False
    haystack = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in haystack for marker in _BUSY_MARKERS)


async def requeue_job(app: str, name: str, args: dict) -> Optional[str]:
    """Resubmit a job that was blocked on a busy resource.

    Deliberately NOT coalesced: each blocked section job must come back as its
    own row. The caller returns normally afterwards, so the current row ends
    non-failed and the tray shows the work as still pending rather than errored.
    """
    try:
        cmd_id = submit_command(app, name, args)
        logger.info(f"requeue_job: requeued {name} (resource busy): {cmd_id}")
        return str(cmd_id)
    except Exception as exc:
        logger.warning(f"requeue_job: failed to requeue {name}: {exc}")
        return None


async def siblings_in_flight(source_id: str, name: str, exclude_id: str) -> bool:
    """True while another job named ``name`` for this source is still pending.

    Used to detect "am I the last one?" for the event-driven phase chain. The
    caller's own row is `running` at that moment, so it must be excluded.
    """
    rows = await repo_query(
        "SELECT count() AS n FROM command "
        "WHERE name = $name AND args.source_id = $sid "
        "AND status IN ['new', 'running'] AND id != $self GROUP ALL",
        {"sid": source_id, "name": name, "self": ensure_record_id(exclude_id)},
    )
    return bool(rows and rows[0].get("n", 0) > 0)


async def submit_command_once(
    app: str, name: str, args: dict, source_id: str
) -> Optional[str]:
    """Submit ``name`` unless a non-terminal job of that name already exists.

    Returns the new command id, or None when the submit was coalesced onto a
    pending job (or failed — fan-out submits are never fatal to the caller).
    """
    try:
        if await command_in_flight(source_id, name):
            logger.info(
                f"submit_command_once: {name} already pending for {source_id}; "
                f"coalescing"
            )
            return None
        cmd_id = submit_command(app, name, args)
        logger.info(f"submit_command_once: submitted {name} for {source_id}: {cmd_id}")
        return str(cmd_id)
    except Exception as exc:
        logger.warning(
            f"submit_command_once: failed to submit {name} for {source_id}: {exc}"
        )
        return None
