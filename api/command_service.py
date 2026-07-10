from typing import Any, Dict, List, Optional

from loguru import logger
from surreal_commands import get_command_status, submit_command


class CommandService:
    """Generic service layer for command operations"""

    @staticmethod
    async def submit_command_job(
        module_name: str,  # Actually app_name for surreal-commands
        command_name: str,
        command_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Submit a generic command job for background processing"""
        try:
            # Ensure command modules are imported before submitting
            # This is needed because submit_command validates against local registry
            try:
                import commands  # noqa: F401 — registers all commands including chat_completion
            except ImportError as import_err:
                logger.error(f"Failed to import command modules: {import_err}")
                raise ValueError("Command modules not available")

            # surreal-commands expects: submit_command(app_name, command_name, args)
            cmd_id = submit_command(
                module_name,  # This is actually the app name (e.g., "open_notebook")
                command_name,  # Command name (e.g., "process_text")
                command_args,  # Input data
            )
            # Convert RecordID to string if needed
            if not cmd_id:
                raise ValueError("Failed to get cmd_id from submit_command")
            cmd_id_str = str(cmd_id)
            logger.info(
                f"Submitted command job: {cmd_id_str} for {module_name}.{command_name}"
            )
            return cmd_id_str

        except Exception as e:
            logger.error(f"Failed to submit command job: {e}")
            raise

    @staticmethod
    async def get_command_status(job_id: str) -> Dict[str, Any]:
        """Get status of any command job — this is the DETAIL fetch (single
        job): unlike list_command_jobs, it returns `progress` WITH its full
        `events[]` log plus `args` (the console reads this directly).
        """
        try:
            status = await get_command_status(job_id)
            progress, args = (
                await CommandService._get_progress_and_args(job_id)
                if status
                else (None, None)
            )
            return {
                "job_id": job_id,
                "status": status.status if status else "unknown",
                "result": status.result if status else None,
                "error_message": getattr(status, "error_message", None)
                if status
                else None,
                "created": str(status.created)
                if status and hasattr(status, "created") and status.created
                else None,
                "updated": str(status.updated)
                if status and hasattr(status, "updated") and status.updated
                else None,
                # surreal_commands' CommandResult doesn't carry `progress`/`args`
                # — we stamp `progress` ourselves via report_job_progress()/
                # append_job_event(), and `args` is the row's stored input.
                "progress": progress,
                "args": args,
            }
        except Exception as e:
            logger.error(f"Failed to get command status: {e}")
            raise

    @staticmethod
    async def _get_progress_and_args(
        job_id: str,
    ) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        from open_notebook.database.repository import ensure_record_id, repo_query

        rows = await repo_query(
            "SELECT progress, args FROM $job_id", {"job_id": ensure_record_id(job_id)}
        )
        if not rows:
            return None, None
        return rows[0].get("progress"), rows[0].get("args")

    @staticmethod
    def _strip_events(progress: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Drop `progress.events[]` for list-endpoint rows — the poller only
        needs `phase`/`tool_name`/`tool_input`; the full log is detail-only.
        """
        if not isinstance(progress, dict) or "events" not in progress:
            return progress
        return {k: v for k, v in progress.items() if k != "events"}

    @staticmethod
    async def list_command_jobs(
        module_filter: Optional[str] = None,
        command_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List command jobs with optional filtering.

        status_filter="active" expands to status IN ['new','running']; any other
        value matches a single status exactly ("failed", "completed", …).
        command_filter filters by command name (exact match).

        Rows written before migration 26 have no `created`, so ordering
        coalesces it to the epoch: timestamped rows come back newest-first and
        the undated legacy rows sort last instead of scrambling the whole list.
        """
        from open_notebook.database.repository import repo_query

        conditions: List[str] = []
        vars: Dict[str, Any] = {}

        if status_filter == "active":
            conditions.append("status IN ['new', 'running']")
        elif status_filter:
            conditions.append("status = $status_val")
            vars["status_val"] = status_filter

        if command_filter:
            conditions.append("name = $name")
            vars["name"] = command_filter

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Clamp to a safe range; embed directly (int — no injection risk).
        safe_limit = max(1, min(int(limit), 1000))

        query = (
            "SELECT id, app, name, args, status, result, error_message, created, updated, progress, "
            "(created ?? d\"1970-01-01T00:00:00Z\") AS sort_ts "
            f"FROM command {where_clause} "
            f"ORDER BY sort_ts DESC LIMIT {safe_limit}"
        )

        try:
            rows = await repo_query(query, vars if vars else None)
            result = []
            for row in rows:
                # Rename id → job_id for consistency with CommandJobStatusResponse.
                # repo_query already stringifies RecordIDs via parse_record_ids.
                job_id = row.pop("id", None)
                result.append(
                    {
                        "job_id": str(job_id) if job_id is not None else None,
                        "name": row.get("name"),
                        "status": row.get("status"),
                        "result": row.get("result"),
                        "error_message": row.get("error_message"),
                        "created": str(row["created"]) if row.get("created") else None,
                        "updated": str(row["updated"]) if row.get("updated") else None,
                        "args": row.get("args"),
                        # Live per-job phase written by long-running commands (e.g.
                        # source ingest → "Parsing PDF with Docling"). None for
                        # commands that don't report progress. The full
                        # `events[]` log is stripped here — list rows stay
                        # small for the poller; only the detail endpoint
                        # (get_command_status) returns events.
                        "progress": CommandService._strip_events(row.get("progress")),
                    }
                )
            return result
        except Exception as e:
            logger.error(f"Failed to list command jobs: {e}")
            raise

    @staticmethod
    async def count_command_jobs() -> Dict[str, int]:
        """Per-status row counts across the whole command table.

        The activity board's list endpoint is capped (LIMIT), so `len(rows)`
        saturates at the cap and reads as frozen while jobs churn underneath.
        This returns the real totals: one entry per status plus an `all` sum.
        Legacy rows spell cancellation both ways ('canceled'/'cancelled');
        they're folded into 'canceled'.
        """
        from open_notebook.database.repository import repo_query

        rows = await repo_query(
            "SELECT status, count() AS n FROM command GROUP BY status"
        )
        counts: Dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "unknown")
            if status == "cancelled":
                status = "canceled"
            counts[status] = counts.get(status, 0) + int(row.get("n") or 0)
        counts["all"] = sum(counts.values())
        return counts

    @staticmethod
    async def cancel_command_job(job_id: str) -> bool:
        """Cancel a queued command job.

        Queued (`new`) jobs are flipped to `canceled` so the worker never picks
        them up. `running` jobs are also flipped — an in-flight executor cannot
        be interrupted and will overwrite the status when it finishes, but
        flipping matters for ORPHANED `running` rows (worker died mid-job),
        which the worker would otherwise re-process on restart.
        """
        from open_notebook.database.repository import ensure_record_id, repo_query

        try:
            rows = await repo_query(
                "UPDATE command SET status = 'canceled', "
                "error_message = 'Canceled by user' "
                "WHERE id = $jid AND status IN ['new', 'running'] RETURN AFTER;",
                {"jid": ensure_record_id(job_id)},
            )
            canceled = bool(rows)
            logger.info(
                f"Cancel job {job_id}: {'canceled' if canceled else 'not cancelable (running or finished)'}"
            )
            return canceled
        except Exception as e:
            logger.error(f"Failed to cancel command job: {e}")
            raise

    @staticmethod
    async def cancel_source_jobs(source_id: str) -> int:
        """Cancel every pending job belonging to a source's processing pipeline.

        Matches on `args.source_id` — every pipeline command (process_source,
        build_blocks, build_sections, verify_*, summarize_*, embed_source,
        generate_source_abstract) carries it. Queued jobs never start; orphaned
        `running` rows (dead worker) are not re-processed on worker restart.
        An actively-executing job cannot be interrupted and will overwrite its
        status when it finishes. Returns the number flipped.
        """
        from open_notebook.database.repository import repo_query

        try:
            rows = await repo_query(
                "UPDATE command SET status = 'canceled', "
                "error_message = 'Canceled by user' "
                "WHERE args.source_id = $sid AND status IN ['new', 'running'] "
                "RETURN AFTER;",
                {"sid": str(source_id)},
            )
            count = len(rows) if rows else 0
            logger.info(f"Canceled {count} pending job(s) for source {source_id}")
            return count
        except Exception as e:
            logger.error(f"Failed to cancel jobs for source {source_id}: {e}")
            raise
