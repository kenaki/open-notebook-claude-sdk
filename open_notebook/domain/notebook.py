import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple, Union

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from surreal_commands import submit_command
from surrealdb import RecordID

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import DatabaseOperationError, InvalidInputError


def _format_outline_chapters(
    outline: List[Dict[str, Any]], _counter: Optional[List[int]] = None
) -> List[str]:
    """
    Flatten a Source.get_outline() tree into "- Ch N: title (pp. X-Y) — summary"
    lines (document-foundation Decision #7/#9). Recurses depth-first so nested
    sub-sections are numbered in reading order alongside their parents.
    """
    counter = _counter if _counter is not None else [0]
    lines: List[str] = []
    for node in outline:
        counter[0] += 1
        title = node.get("title") or "Untitled"
        page_start = node.get("page_start")
        page_end = node.get("page_end")
        if page_start is not None and page_end is not None:
            page_range = f" (pp. {page_start}–{page_end})"
        elif page_start is not None:
            page_range = f" (p. {page_start})"
        else:
            page_range = ""
        summary = node.get("summary")
        summary_part = f" — {summary}" if summary else ""
        lines.append(f"- Ch {counter[0]}: {title}{page_range}{summary_part}")
        children = node.get("children") or []
        if children:
            lines.extend(_format_outline_chapters(children, counter))
    return lines


def format_source_long_context(source_context: Dict[str, Any]) -> str:
    """
    Render a Source.get_context("long") dict as an "Abstract" + flattened
    "Chapters" text block for a chaptered source (document-foundation Decision
    #7/#9), or the raw body for a non-chaptered source (Decision #12 fallback —
    the dict then carries full_text instead of abstract/outline).
    """
    parts: List[str] = []
    abstract = source_context.get("abstract")
    if abstract:
        parts.append(f"Abstract: {abstract}")
    chapter_lines = _format_outline_chapters(source_context.get("outline") or [])
    if chapter_lines:
        parts.append("Chapters:\n" + "\n".join(chapter_lines))
    if not chapter_lines and not abstract:
        # Decision #12: a non-chaptered source (web page / pasted text / transcript,
        # or a not-yet-chaptered PDF) keeps its raw body in long context.
        full_text = source_context.get("full_text")
        if full_text:
            parts.append(full_text)
    return "\n\n".join(parts).strip()


class Notebook(ObjectModel):
    table_name: ClassVar[str] = "notebook"
    name: str
    description: str
    archived: Optional[bool] = False
    # Notebook-wide tag → color-key map for the chat gallery's grouping tags
    # (e.g. {"grammar": "violet"}). Keys are lowercased tag names; values are
    # palette keys the frontend resolves to styles. Empty for old notebooks.
    chat_tag_colors: Dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v):
        if not v.strip():
            raise InvalidInputError("Notebook name cannot be empty")
        return v

    async def get_sources(self, include_full_text: bool = False) -> List["Source"]:
        try:
            source_projection = "" if include_full_text else " omit source.full_text"
            srcs = await repo_query(
                f"""
                select *{source_projection} from (
                select in as source from reference where out=$id
                fetch source
            ) order by source.updated desc
            """,
                {"id": ensure_record_id(self.id)},
            )
            return [Source(**src["source"]) for src in srcs] if srcs else []
        except Exception as e:
            logger.error(f"Error fetching sources for notebook {self.id}: {str(e)}")
            logger.exception(e)
            raise DatabaseOperationError(e)

    async def get_notes(self, include_content: bool = False) -> List["Note"]:
        try:
            note_projection = (
                " omit note.embedding"
                if include_content
                else " omit note.content, note.embedding"
            )
            srcs = await repo_query(
                f"""
            select *{note_projection} from (
                select in as note from artifact where out=$id
                fetch note
            ) order by note.updated desc
            """,
                {"id": ensure_record_id(self.id)},
            )
            return [Note(**src["note"]) for src in srcs] if srcs else []
        except Exception as e:
            logger.error(f"Error fetching notes for notebook {self.id}: {str(e)}")
            logger.exception(e)
            raise DatabaseOperationError(e)

    async def get_context(self) -> str:
        """
        Build long-form notebook context for podcast and LLM workflows.

        Normal list retrieval omits large source/note bodies, so this method uses
        opt-in full-content fetches and formats only substantive context blocks.
        Chaptered sources are digested via title + abstract + chapter outline
        (tiered context, Decision #7/#9); non-chaptered sources fall back to their
        raw body (Decision #12), so full_text is fetched to make that fallback work.
        """
        sources = await self.get_sources(include_full_text=True)
        notes = await self.get_notes(include_content=True)
        context_blocks = []

        for source in sources:
            source_context = await source.get_context(context_size="long")
            if isinstance(source_context, dict):
                title = source_context.get("title") or source.title or "Untitled source"
                insights = source_context.get("insights") or []

                content_parts = []
                # Tiered context: chaptered sources → abstract + chapter outline
                # (Decision #7/#9; never the raw blob, so textbooks don't balloon
                # the prompt); non-chaptered sources → raw body (Decision #12).
                outline_block = format_source_long_context(source_context)
                if outline_block:
                    content_parts.append(outline_block)

                insight_lines = []
                for insight in insights:
                    if not isinstance(insight, dict):
                        continue

                    insight_content = insight.get("content")
                    if not insight_content:
                        continue

                    insight_type = insight.get("insight_type") or "Insight"
                    insight_lines.append(f"- {insight_type}: {insight_content}")

                if insight_lines:
                    content_parts.append("Insights:\n" + "\n".join(insight_lines))

                content = "\n\n".join(content_parts).strip()
            else:
                title = source.title or "Untitled source"
                content = str(source_context).strip()

            if content:
                context_blocks.append(f"## Source: {title}\n\n{content}")

        for note in notes:
            note_context = note.get_context(context_size="long")
            if isinstance(note_context, dict):
                title = note_context.get("title") or note.title or "Untitled note"
                content = note_context.get("content")
                content = str(content).strip() if content else ""
            else:
                title = note.title or "Untitled note"
                content = str(note_context).strip()

            if content:
                context_blocks.append(f"## Note: {title}\n\n{content}")

        return "\n\n".join(context_blocks)

    async def get_chat_sessions(self) -> List["ChatSession"]:
        try:
            srcs = await repo_query(
                """
                select * from (
                    select
                    <- chat_session as chat_session
                    from refers_to
                    where out=$id
                    fetch chat_session
                )
                order by chat_session.updated desc
            """,
                {"id": ensure_record_id(self.id)},
            )
            return (
                [ChatSession(**src["chat_session"][0]) for src in srcs] if srcs else []
            )
        except Exception as e:
            logger.error(
                f"Error fetching chat sessions for notebook {self.id}: {str(e)}"
            )
            logger.exception(e)
            raise DatabaseOperationError(e)

    async def get_delete_preview(self) -> Dict[str, Any]:
        """
        Get counts of items that would be affected by deleting this notebook.

        Returns a dict with:
        - note_count: Number of notes that will be deleted
        - exclusive_source_count: Sources only in this notebook (can be deleted)
        - shared_source_count: Sources in other notebooks (will be unlinked only)
        """
        try:
            notebook_id = ensure_record_id(self.id)

            # Count notes
            note_result = await repo_query(
                "SELECT count() as count FROM artifact WHERE out = $notebook_id GROUP ALL",
                {"notebook_id": notebook_id},
            )
            note_count = note_result[0]["count"] if note_result else 0

            # Get sources with count of references to OTHER notebooks
            # If assigned_others = 0, source is exclusive to this notebook
            # If assigned_others > 0, source is shared with other notebooks
            source_counts = await repo_query(
                """
                SELECT
                    id,
                    count(->reference[WHERE out != $notebook_id].out) as assigned_others
                FROM (SELECT VALUE <-reference.in AS sources FROM $notebook_id)[0]
                """,
                {"notebook_id": notebook_id},
            )

            exclusive_count = 0
            shared_count = 0
            for src in source_counts:
                if src.get("assigned_others", 0) == 0:
                    exclusive_count += 1
                else:
                    shared_count += 1

            return {
                "note_count": note_count,
                "exclusive_source_count": exclusive_count,
                "shared_source_count": shared_count,
            }
        except Exception as e:
            logger.error(f"Error getting delete preview for notebook {self.id}: {e}")
            logger.exception(e)
            raise DatabaseOperationError(e)

    async def delete(self, delete_exclusive_sources: bool = False) -> Dict[str, int]:
        """
        Delete notebook with cascade deletion of notes and optional source deletion.

        Args:
            delete_exclusive_sources: If True, also delete sources that belong
                                     only to this notebook. Default is False.

        Returns:
            Dict with counts: deleted_notes, deleted_sources, unlinked_sources
        """
        if self.id is None:
            raise InvalidInputError("Cannot delete notebook without an ID")

        try:
            notebook_id = ensure_record_id(self.id)
            deleted_notes = 0
            deleted_sources = 0
            unlinked_sources = 0

            # 1. Get and delete all notes linked to this notebook
            notes = await self.get_notes()
            for note in notes:
                await note.delete()
                deleted_notes += 1
            logger.info(f"Deleted {deleted_notes} notes for notebook {self.id}")

            # Delete artifact relationships
            await repo_query(
                "DELETE artifact WHERE out = $notebook_id",
                {"notebook_id": notebook_id},
            )

            # 2. Handle sources
            if delete_exclusive_sources:
                # Find sources with count of references to OTHER notebooks
                # If assigned_others = 0, source is exclusive to this notebook
                source_counts = await repo_query(
                    """
                    SELECT
                        id,
                        count(->reference[WHERE out != $notebook_id].out) as assigned_others
                    FROM (SELECT VALUE <-reference.in AS sources FROM $notebook_id)[0]
                    """,
                    {"notebook_id": notebook_id},
                )

                for src in source_counts:
                    source_id = src.get("id")
                    if source_id and src.get("assigned_others", 0) == 0:
                        # Exclusive source - delete it
                        try:
                            source = await Source.get(str(source_id))
                            await source.delete()
                            deleted_sources += 1
                        except Exception as e:
                            logger.warning(
                                f"Failed to delete exclusive source {source_id}: {e}"
                            )
                    else:
                        unlinked_sources += 1
            else:
                # Just count sources that will be unlinked
                source_result = await repo_query(
                    "SELECT count() as count FROM reference WHERE out = $notebook_id GROUP ALL",
                    {"notebook_id": notebook_id},
                )
                unlinked_sources = source_result[0]["count"] if source_result else 0

            # Delete reference relationships (unlink all sources)
            await repo_query(
                "DELETE reference WHERE out = $notebook_id",
                {"notebook_id": notebook_id},
            )
            logger.info(
                f"Unlinked {unlinked_sources} sources, deleted {deleted_sources} "
                f"exclusive sources for notebook {self.id}"
            )

            # 3. Delete the notebook record itself
            await super().delete()
            logger.info(f"Deleted notebook {self.id}")

            return {
                "deleted_notes": deleted_notes,
                "deleted_sources": deleted_sources,
                "unlinked_sources": unlinked_sources,
            }

        except Exception as e:
            logger.error(f"Error deleting notebook {self.id}: {e}")
            logger.exception(e)
            raise DatabaseOperationError(f"Failed to delete notebook: {e}")


class Asset(BaseModel):
    file_path: Optional[str] = None
    url: Optional[str] = None


class SourceEmbedding(ObjectModel):
    table_name: ClassVar[str] = "source_embedding"
    content: str

    async def get_source(self) -> "Source":
        try:
            src = await repo_query(
                """
            select source.* from $id fetch source
            """,
                {"id": ensure_record_id(self.id)},
            )
            return Source(**src[0]["source"])
        except Exception as e:
            logger.error(f"Error fetching source for embedding {self.id}: {str(e)}")
            logger.exception(e)
            raise DatabaseOperationError(e)


class SourceInsight(ObjectModel):
    table_name: ClassVar[str] = "source_insight"
    insight_type: str
    content: str

    async def get_source(self) -> "Source":
        try:
            src = await repo_query(
                """
            select source.* from $id fetch source
            """,
                {"id": ensure_record_id(self.id)},
            )
            return Source(**src[0]["source"])
        except Exception as e:
            logger.error(f"Error fetching source for insight {self.id}: {str(e)}")
            logger.exception(e)
            raise DatabaseOperationError(e)

    async def save_as_note(self, notebook_id: Optional[str] = None) -> Any:
        source = await self.get_source()
        note = Note(
            title=f"{self.insight_type} from source {source.title}",
            content=self.content,
        )
        await note.save()
        if notebook_id:
            await note.add_to_notebook(notebook_id)
        return note


class SourceSection(ObjectModel):
    table_name = "source_section"
    source: Optional[str] = None
    parent: Optional[str] = None
    order: int = 0
    level: int = 0
    title: str = ""
    content: str = ""
    cleaned_content: Optional[str] = None
    summary: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    token_count: Optional[int] = None
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    nullable_fields = ["parent", "cleaned_content", "summary", "page_start", "page_end", "token_count", "created", "updated"]


def _flatten_section_ids(nodes: List[Dict]) -> List[str]:
    """Depth-first flatten of a ``get_sections()``/``get_outline()`` tree into
    a list of section ids, document order. Shared helper for
    ``Source.summarize_sections()`` (B3).
    """
    ids: List[str] = []
    for node in nodes:
        nid = node.get("id")
        if nid:
            ids.append(str(nid))
        ids.extend(_flatten_section_ids(node.get("children") or []))
    return ids


class Source(ObjectModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    table_name: ClassVar[str] = "source"
    nullable_fields: ClassVar[set[str]] = {"page_offset", "page_labels", "page_map"}
    asset: Optional[Asset] = None
    title: Optional[str] = None
    topics: Optional[List[str]] = Field(default_factory=list)
    full_text: Optional[str] = None
    page_offset: Optional[int] = None
    page_labels: Optional[dict] = None
    # Phase3: persisted per-block page provenance from Docling extraction (A2).
    # Null for non-PDF / pre-Docling sources. Read back by embed_source /
    # backfill_page_numbers to stamp page_number on each source_embedding row.
    page_map: Optional[list] = None
    command: Optional[Union[str, RecordID]] = Field(
        default=None, description="Link to surreal-commands processing job"
    )

    @field_validator("command", mode="before")
    @classmethod
    def parse_command(cls, value):
        """Parse command field to ensure RecordID format"""
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value

    @field_validator("id", mode="before")
    @classmethod
    def parse_id(cls, value):
        """Parse id field to handle both string and RecordID inputs"""
        if value is None:
            return None
        if isinstance(value, RecordID):
            return str(value)
        return str(value) if value else None

    async def get_status(self) -> Optional[str]:
        """Get the processing status of the associated command"""
        if not self.command:
            return None

        try:
            from surreal_commands import get_command_status

            status = await get_command_status(str(self.command))
            return status.status if status else "unknown"
        except Exception as e:
            logger.warning(f"Failed to get command status for {self.command}: {e}")
            return "unknown"

    async def get_processing_progress(self) -> Optional[Dict[str, Any]]:
        """Get detailed processing information for the associated command"""
        if not self.command:
            return None

        try:
            from surreal_commands import get_command_status

            status_result = await get_command_status(str(self.command))
            if not status_result:
                return None

            # Extract execution metadata if available
            result = getattr(status_result, "result", None)
            execution_metadata = (
                result.get("execution_metadata", {}) if isinstance(result, dict) else {}
            )

            return {
                "status": status_result.status,
                "started_at": execution_metadata.get("started_at"),
                "completed_at": execution_metadata.get("completed_at"),
                "error": getattr(status_result, "error_message", None),
                "result": result,
            }
        except Exception as e:
            logger.warning(f"Failed to get command progress for {self.command}: {e}")
            return None

    async def get_context(
        self, context_size: Literal["short", "long"] = "short"
    ) -> Dict[str, Any]:
        """
        Build LLM-facing context for this source.

        "short" is a lightweight pointer (id/title/insights) for retrieval-style
        prompts. "long" is the tiered digest (document-foundation Decision #7/#9):
        title + insights + doc abstract + chapter outline (titles, page ranges,
        summaries) — it never includes the raw full_text blob, so a textbook-sized
        source no longer balloons the prompt. Detail retrieval for specific
        passages goes through vector_search / the agent's get_section tool
        instead.
        """
        insights_list = await self.get_insights()
        insights = [insight.model_dump() for insight in insights_list]
        if context_size == "long":
            outline = await self.get_outline()
            # Decision #7/#9: chaptered sources (PDFs) return the tiered digest
            # (abstract + chapter outline), never the raw full_text blob. Decision
            # #12: sources that never chapter — web pages, pasted text, transcripts,
            # or a PDF whose chaptering job hasn't completed yet — keep their raw
            # body so their content still reaches chat/podcast context. An empty
            # outline is the signal for that fallback.
            if not outline:
                return dict(
                    id=self.id,
                    title=self.title,
                    insights=insights,
                    full_text=self.full_text,
                )
            abstract_insight = next(
                (i for i in insights_list if i.insight_type == "abstract"), None
            )
            return dict(
                id=self.id,
                title=self.title,
                insights=insights,
                abstract=abstract_insight.content if abstract_insight else None,
                outline=outline,
            )
        else:
            return dict(id=self.id, title=self.title, insights=insights)

    async def get_embedded_chunks(self) -> int:
        try:
            result = await repo_query(
                """
                select count() as chunks from source_embedding where source=$id GROUP ALL
                """,
                {"id": ensure_record_id(self.id)},
            )
            if len(result) == 0:
                return 0
            return result[0]["chunks"]
        except Exception as e:
            logger.error(f"Error fetching chunks count for source {self.id}: {str(e)}")
            logger.exception(e)
            raise DatabaseOperationError(f"Failed to count chunks for source: {str(e)}")

    async def get_insights(self) -> List[SourceInsight]:
        try:
            result = await repo_query(
                """
                SELECT * FROM source_insight WHERE source=$id
                """,
                {"id": ensure_record_id(self.id)},
            )
            return [SourceInsight(**insight) for insight in result]
        except Exception as e:
            logger.error(f"Error fetching insights for source {self.id}: {str(e)}")
            logger.exception(e)
            raise DatabaseOperationError("Failed to fetch insights for source")

    async def get_sections(self) -> List[Dict]:
        """
        Return source_section records as a nested tree.

        Each node dict contains all section fields plus a 'children' key
        holding a list of child nodes (recursive).  Roots are returned in
        document order (ORDER BY order in the query).
        """
        try:
            rows = await repo_query(
                "SELECT * FROM source_section WHERE source = $sid ORDER BY order",
                {"sid": ensure_record_id(self.id)},
            )
        except Exception as exc:
            logger.error(f"Error fetching sections for source {self.id}: {exc}")
            logger.exception(exc)
            raise DatabaseOperationError("Failed to fetch sections for source")

        if not rows:
            return []

        # Build id → node map; add 'children' list to each node
        by_id: Dict[str, Dict] = {}
        for row in rows:
            node = dict(row)
            node["id"] = str(row["id"])
            node["children"] = []
            by_id[node["id"]] = node

        # Wire children; collect roots
        roots: List[Dict] = []
        for row in rows:
            node = by_id[str(row["id"])]
            parent = row.get("parent")
            if parent:
                parent_id = str(parent)
                if parent_id in by_id:
                    by_id[parent_id]["children"].append(node)
                else:
                    roots.append(node)  # orphan → treat as root
            else:
                roots.append(node)

        return roots

    async def get_outline(self) -> List[Dict]:
        """
        Return section outline (no content) as a nested tree.

        Each node: {id, title, level, order, page_start, page_end, summary, children}.
        Used for the agent context (chapter-summary outline) and the TOC sidebar.
        """
        try:
            rows = await repo_query(
                "SELECT id, title, level, order, page_start, page_end, summary, parent "
                "FROM source_section WHERE source = $sid ORDER BY order",
                {"sid": ensure_record_id(self.id)},
            )
        except Exception as exc:
            logger.error(f"Error fetching outline for source {self.id}: {exc}")
            logger.exception(exc)
            raise DatabaseOperationError("Failed to fetch outline for source")

        if not rows:
            return []

        by_id: Dict[str, Dict] = {}
        for row in rows:
            node = {
                "id": str(row["id"]),
                "title": row.get("title", ""),
                "level": row.get("level", 1),
                "order": row.get("order", 0),
                "page_start": row.get("page_start"),
                "page_end": row.get("page_end"),
                "summary": row.get("summary"),
                "children": [],
            }
            by_id[node["id"]] = node

        roots: List[Dict] = []
        for row in rows:
            node = by_id[str(row["id"])]
            parent = row.get("parent")
            if parent:
                parent_id = str(parent)
                if parent_id in by_id:
                    by_id[parent_id]["children"].append(node)
                else:
                    roots.append(node)
            else:
                roots.append(node)

        return roots

    async def add_to_notebook(self, notebook_id: str) -> Any:
        if not notebook_id:
            raise InvalidInputError("Notebook ID must be provided")
        return await self.relate("reference", notebook_id)

    async def vectorize(self) -> str:
        """
        Submit vectorization as a background job using the embed_source command.

        This method leverages the job-based architecture to prevent HTTP connection
        pool exhaustion when processing large documents. The embed_source command:
        1. Detects content type from file path
        2. Chunks text using content-type aware splitter
        3. Generates all embeddings in batches
        4. Bulk inserts source_embedding records

        Returns:
            str: The command/job ID that can be used to track progress via the commands API

        Raises:
            ValueError: If source has no text to vectorize
            DatabaseOperationError: If job submission fails
        """
        logger.info(f"Submitting embed_source job for source {self.id}")

        try:
            if not self.full_text or not self.full_text.strip():
                raise ValueError(f"Source {self.id} has no text to vectorize")

            # Submit the embed_source command
            command_id = submit_command(
                "open_notebook",
                "embed_source",
                {"source_id": str(self.id)},
            )

            command_id_str = str(command_id)
            logger.info(
                f"Embed source job submitted for source {self.id}: "
                f"command_id={command_id_str}"
            )

            return command_id_str

        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Failed to submit embed_source job for source {self.id}: {e}"
            )
            logger.exception(e)
            raise DatabaseOperationError(e)

    async def add_insight(self, insight_type: str, content: str) -> Optional[str]:
        """
        Submit insight creation as an async command (fire-and-forget).

        Submits a create_insight command that handles database operations with
        automatic retry logic for transaction conflicts. The command also submits
        an embed_insight command for async embedding.

        This method returns immediately after submitting the command - it does NOT
        wait for the insight to be created. Use this for batch operations where
        throughput is more important than immediate confirmation.

        Args:
            insight_type: Type/category of the insight
            content: The insight content text

        Returns:
            command_id for optional tracking, or None if submission failed

        Raises:
            InvalidInputError: If insight_type or content is empty
        """
        if not insight_type or not content:
            raise InvalidInputError("Insight type and content must be provided")

        try:
            # Submit create_insight command (fire-and-forget)
            # Command handles retries internally for transaction conflicts
            command_id = submit_command(
                "open_notebook",
                "create_insight",
                {
                    "source_id": str(self.id),
                    "insight_type": insight_type,
                    "content": content,
                },
            )
            logger.info(
                f"Submitted create_insight command {command_id} for source {self.id} "
                f"(type={insight_type})"
            )
            return str(command_id)

        except Exception as e:
            logger.error(f"Error submitting create_insight for source {self.id}: {e}")
            return None

    async def summarize_sections(self) -> List[str]:
        """
        Fan out one ``summarize_section`` background job per section, then
        submit ``generate_source_abstract`` to roll the summaries up into a
        document-level abstract once they land (B3).

        Fire-and-forget (Decisions #4/#7): returns immediately without
        waiting for any job to complete. ``generate_source_abstract`` retries
        with backoff until every text-bearing section has a summary (see
        ``commands/summary_commands.py``), so the two submissions here don't
        need to be ordered/awaited relative to each other. Safe to call again
        manually — summaries are overwritten in place and the abstract
        insight is replaced (not duplicated) on each regeneration.

        Returns:
            List[str]: command_ids of every job submitted (sections then
            abstract), in submission order. A submit failure for one section
            is logged and skipped rather than aborting the rest.
        """
        tree = await self.get_sections()
        section_ids = _flatten_section_ids(tree)

        command_ids: List[str] = []
        for section_id in section_ids:
            try:
                cmd_id = submit_command(
                    "open_notebook",
                    "summarize_section",
                    {"source_section_id": section_id},
                )
                command_ids.append(str(cmd_id))
            except Exception as e:
                logger.warning(
                    f"Failed to submit summarize_section for {section_id}: {e}"
                )

        try:
            abstract_cmd_id = submit_command(
                "open_notebook",
                "generate_source_abstract",
                {"source_id": str(self.id)},
            )
            command_ids.append(str(abstract_cmd_id))
        except Exception as e:
            logger.warning(
                f"Failed to submit generate_source_abstract for {self.id}: {e}"
            )

        return command_ids

    def _prepare_save_data(self) -> dict:
        """Override to ensure command field is always RecordID format for database"""
        data = super()._prepare_save_data()

        # Ensure command field is RecordID format if not None
        if data.get("command") is not None:
            data["command"] = ensure_record_id(data["command"])

        return data

    async def delete(self) -> bool:
        """Delete source and clean up associated file, embeddings, and insights."""
        # Clean up uploaded file if it exists
        if self.asset and self.asset.file_path:
            file_path = Path(self.asset.file_path)
            if file_path.exists():
                try:
                    os.unlink(file_path)
                    logger.info(f"Deleted file for source {self.id}: {file_path}")
                except Exception as e:
                    logger.warning(
                        f"Failed to delete file {file_path} for source {self.id}: {e}. "
                        "Continuing with database deletion."
                    )
            else:
                logger.debug(
                    f"File {file_path} not found for source {self.id}, skipping cleanup"
                )

        # Delete associated embeddings and insights to prevent orphaned records
        try:
            source_id = ensure_record_id(self.id)
            await repo_query(
                "DELETE source_embedding WHERE source = $source_id",
                {"source_id": source_id},
            )
            await repo_query(
                "DELETE source_insight WHERE source = $source_id",
                {"source_id": source_id},
            )
            logger.debug(f"Deleted embeddings and insights for source {self.id}")
        except Exception as e:
            logger.warning(
                f"Failed to delete embeddings/insights for source {self.id}: {e}. "
                "Continuing with source deletion."
            )

        # Call parent delete to remove database record
        return await super().delete()


class Note(ObjectModel):
    table_name: ClassVar[str] = "note"
    title: Optional[str] = None
    note_type: Optional[Literal["human", "ai"]] = None
    content: Optional[str] = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v):
        if v is not None and not v.strip():
            raise InvalidInputError("Note content cannot be empty")
        return v

    async def save(self) -> Optional[str]:
        """
        Save the note and submit embedding command.

        Overrides ObjectModel.save() to submit an async embed_note command
        after saving, instead of inline embedding.

        Returns:
            Optional[str]: The command_id if embedding was submitted, None otherwise
        """
        # Call parent save (without embedding)
        await super().save()

        # Submit embedding command (fire-and-forget) if note has content
        if self.id and self.content and self.content.strip():
            command_id = submit_command(
                "open_notebook",
                "embed_note",
                {"note_id": str(self.id)},
            )
            logger.debug(f"Submitted embed_note command {command_id} for {self.id}")
            return command_id

        return None

    async def add_to_notebook(self, notebook_id: str) -> Any:
        if not notebook_id:
            raise InvalidInputError("Notebook ID must be provided")
        return await self.relate("artifact", notebook_id)

    def get_context(
        self, context_size: Literal["short", "long"] = "short"
    ) -> Dict[str, Any]:
        if context_size == "long":
            return dict(id=self.id, title=self.title, content=self.content)
        else:
            return dict(
                id=self.id,
                title=self.title,
                content=self.content[:100] if self.content else None,
            )


class ChatSession(ObjectModel):
    table_name: ClassVar[str] = "chat_session"
    nullable_fields: ClassVar[set[str]] = {
        "model_override",
        "parent_session_id",
        "quote",
    }
    title: Optional[str] = None
    model_override: Optional[str] = None
    parent_session_id: Optional[str] = None
    quote: Optional[str] = None
    # User-assigned grouping tags (many per chat). Drives the gallery's group
    # filter + search. Defaults to an empty list so old sessions read cleanly.
    tags: List[str] = Field(default_factory=list)

    async def relate_to_notebook(self, notebook_id: str) -> Any:
        if not notebook_id:
            raise InvalidInputError("Notebook ID must be provided")
        return await self.relate("refers_to", notebook_id)

    async def relate_to_source(self, source_id: str) -> Any:
        if not source_id:
            raise InvalidInputError("Source ID must be provided")
        return await self.relate("refers_to", source_id)

    async def get_notebook_id(self) -> Optional[str]:
        """Return the notebook this session is linked to via refers_to, or None."""
        results = await repo_query(
            "SELECT out FROM refers_to WHERE in = $id",
            {"id": ensure_record_id(self.id)},
        )
        return results[0]["out"] if results else None

    @classmethod
    async def get_ids_for_source(cls, source_id: str) -> List[str]:
        """Return session IDs that refer_to the given source_id."""
        results = await repo_query(
            "SELECT in FROM refers_to WHERE out = $source_id",
            {"source_id": ensure_record_id(source_id)},
        )
        return [r["in"] for r in results]


async def text_search(
    keyword: str, results: int, source: bool = True, note: bool = True
):
    if not keyword:
        raise InvalidInputError("Search keyword cannot be empty")
    try:
        search_results = await repo_query(
            """
            select *
            from fn::text_search($keyword, $results, $source, $note)
            """,
            {"keyword": keyword, "results": results, "source": source, "note": note},
        )
        return search_results
    except RuntimeError as e:
        # SurrealDB's search::highlight can compute a byte position that exceeds the
        # stored string length on large or multi-byte chunks, aborting the whole query
        # ("position overflow"). Fall back to vector search so the user still gets
        # results instead of a 500. See issue #648.
        if "position overflow" in str(e):
            logger.warning(
                f"Highlight position overflow, falling back to vector search: {str(e)}"
            )
            try:
                return await vector_search(keyword, results, source, note)
            except Exception as ve:
                # Both search paths failed (e.g. no embedding model configured).
                # Surface the failure instead of returning [] — an empty list would
                # be indistinguishable from a legitimate "no matches" and mask a
                # total search outage from callers.
                logger.error(f"Vector search fallback also failed: {str(ve)}")
                logger.exception(ve)
                raise DatabaseOperationError(ve)
        logger.error(f"Error performing text search: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)
    except Exception as e:
        logger.error(f"Error performing text search: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)


async def vector_search(
    keyword: str,
    results: int,
    source: bool = True,
    note: bool = True,
    minimum_score=0.2,
):
    if not keyword:
        raise InvalidInputError("Search keyword cannot be empty")
    try:
        from open_notebook.utils.embedding import generate_embedding

        # Use unified embedding function (handles chunking if query is very long)
        embed = await generate_embedding(keyword)
        search_results = await repo_query(
            """
            SELECT * FROM fn::vector_search($embed, $results, $source, $note, $minimum_score);
            """,
            {
                "embed": embed,
                "results": results,
                "source": source,
                "note": note,
                "minimum_score": minimum_score,
            },
        )
        # Phase3: fn::vector_search now also returns page_number + bbox per row
        # (populated for source_embedding matches; NONE for insight/note rows).
        # Normalise so downstream callers can rely on the keys existing without
        # crashing on older DBs whose function predates the migration-20 redefine.
        for row in search_results or []:
            if isinstance(row, dict):
                row.setdefault("page_number", None)
                row.setdefault("bbox", None)
        return search_results
    except Exception as e:
        logger.error(f"Error performing vector search: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)
