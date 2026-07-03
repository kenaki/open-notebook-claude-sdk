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
        """Get status of any command job"""
        try:
            status = await get_command_status(job_id)
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
                # surreal_commands' CommandResult doesn't carry the `progress`
                # field we stamp via report_job_progress(), so fetch it directly.
                "progress": await CommandService._get_progress(job_id)
                if status
                else None,
            }
        except Exception as e:
            logger.error(f"Failed to get command status: {e}")
            raise

    @staticmethod
    async def _get_progress(job_id: str) -> Optional[Dict[str, Any]]:
        from open_notebook.database.repository import ensure_record_id, repo_query

        rows = await repo_query(
            "SELECT progress FROM $job_id", {"job_id": ensure_record_id(job_id)}
        )
        return rows[0].get("progress") if rows else None

    @staticmethod
    async def list_command_jobs(
        module_filter: Optional[str] = None,
        command_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List command jobs with optional filtering.

        status_filter="active" expands to status IN ['new','running'].
        command_filter filters by command name (exact match).
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
            "SELECT id, app, name, args, status, result, error_message, created, updated, progress "
            f"FROM command {where_clause} "
            f"ORDER BY created DESC LIMIT {safe_limit}"
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
                        # commands that don't report progress.
                        "progress": row.get("progress"),
                    }
                )
            return result
        except Exception as e:
            logger.error(f"Failed to list command jobs: {e}")
            raise

    @staticmethod
    async def cancel_command_job(job_id: str) -> bool:
        """Cancel a running command job"""
        try:
            # Implementation depends on surreal-commands cancellation support
            # For now, just log the attempt
            logger.info(f"Attempting to cancel job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel command job: {e}")
            raise
