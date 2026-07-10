"""Shared annotation-reference resolver for chat surfaces.

Both the source-chat and the notebook-chat send paths let a user point the model
at specific highlights. This module holds the ONE resolver they share
(cross-interface-study Decision #7): it records the ``cites_annotation`` edge,
fetches each annotation's block window (±3, one round trip) for the AI-context
section, and returns a compact refs list for the UI pills.

The two surfaces differ only in (a) which annotations they accept and (b) how
they obtain the owning ``Source``, so both are injected:

- ``check_ownership(annotation) -> bool`` — source chat: the annotation's source
  IS this source; notebook chat: the annotation's source is a member of this
  notebook (via the ``reference`` edge). Foreign/invalid ids are skipped, never
  fatal.
- ``resolve_source(annotation) -> Source | None`` — source chat already holds the
  single Source; notebook chat fetches (and caches) each annotation's Source,
  because one tag-ask may span several sources.

Ref dicts carry ``source_id`` on BOTH paths (Decision #6) so notebook-chat pills,
which span sources, each know their own jump target.
"""

from typing import Awaitable, Callable, List, Optional

from loguru import logger

from api.routers._helpers import ensure_prefix
from open_notebook.database.repository import (
    ensure_record_id,
    repo_query,
    repo_relate,
)
from open_notebook.domain import blocks
from open_notebook.domain.notebook import Source, SourceAnnotation
from open_notebook.exceptions import NotFoundError
from open_notebook.graphs.source_chat import (
    annotation_block_content,
    build_annotation_context_section,
)

# Cap referenced annotations per message so a tag-ask over a large tag can't blow
# the agent context (default 10; source-chat Open Question Q-tag-ask-limit).
MAX_ANNOTATION_REFS = 10


async def relate_citation(full_session_id: str, annotation_id: str) -> None:
    """Record a ``chat_session->cites_annotation->source_annotation`` edge once.

    SELECT-checks first so re-referencing the same annotation across turns does
    not pile up duplicate edges (db-design §2.4 / §3b)."""
    existing = await repo_query(
        "SELECT id FROM cites_annotation WHERE in = $s AND out = $a LIMIT 1",
        {"s": ensure_record_id(full_session_id), "a": ensure_record_id(annotation_id)},
    )
    if not existing:
        await repo_relate(full_session_id, "cites_annotation", annotation_id)


async def resolve_annotations_for_chat(
    annotation_ids: List[str],
    full_session_id: str,
    *,
    check_ownership: Callable[[SourceAnnotation], Awaitable[bool]],
    resolve_source: Callable[[SourceAnnotation], Awaitable[Optional[Source]]],
) -> tuple[str, List[dict]]:
    """Resolve referenced annotations into ``(context_section, annotation_refs)``.

    For each annotation that passes ``check_ownership`` (invalid/foreign ids are
    skipped, not fatal): records the ``cites_annotation`` edge, then — if the
    annotation is block-anchored and its source is available — fetches its block
    window (radius 3, one round trip, db-design §3b) and renders the anchored
    block's content; otherwise falls back to the stored quote + page. Returns the
    structured context block for the prompt and a compact refs list (each ref
    carries ``source_id`` so cross-source pills know their jump target).
    """
    resolved: List[dict] = []
    refs: List[dict] = []
    for raw_id in annotation_ids[:MAX_ANNOTATION_REFS]:
        annotation_id = ensure_prefix(raw_id, "source_annotation")
        try:
            annotation = await SourceAnnotation.get(annotation_id)
        except NotFoundError:
            logger.warning(f"Skipping unknown annotation ref {annotation_id}")
            continue
        if not await check_ownership(annotation):
            logger.warning(
                f"Skipping annotation {annotation_id}: failed ownership check"
            )
            continue

        await relate_citation(full_session_id, annotation_id)

        source = await resolve_source(annotation)
        src_id = str(annotation.source) if annotation.source else ""
        parse_gen = source.parse_generation if source else None

        item = {
            "section_path": [],
            "content": annotation.quote or "",
            "note": annotation.note,
        }
        if annotation.block_seq is not None and parse_gen is not None:
            src_key = src_id.split(":", 1)[1] if ":" in src_id else src_id
            gen = (
                annotation.anchor_gen
                if annotation.anchor_gen is not None
                else parse_gen
            )
            window = await blocks.get_window(
                src_key, gen, annotation.block_seq, radius=3
            )
            block = next(
                (b for b in window if b.get("seq") == annotation.block_seq), None
            )
            if block:
                item["section_path"] = block.get("section_path") or []
                item["content"] = annotation_block_content(block, annotation.quote)
        resolved.append(item)
        refs.append(
            {
                "id": annotation.id,
                "source_id": src_id,
                "quote": annotation.quote,
                "block_seq": annotation.block_seq,
                "page": annotation.page,
            }
        )

    return build_annotation_context_section(resolved), refs


def make_source_in_notebook_check(
    notebook_id: str,
) -> Callable[[SourceAnnotation], Awaitable[bool]]:
    """Ownership check for notebook chat: the annotation's source must belong to
    ``notebook_id`` (the ``reference`` edge ``source -> notebook``).

    Caches the per-source verdict for the request so a tag-ask spanning several
    annotations of the same source runs one membership query, not N.
    """
    cache: dict[str, bool] = {}

    async def check(annotation: SourceAnnotation) -> bool:
        source_id = str(annotation.source) if annotation.source else None
        if not source_id:
            return False
        if source_id not in cache:
            rows = await repo_query(
                "SELECT id FROM reference WHERE in = $source_id AND out = $notebook_id",
                {
                    "source_id": ensure_record_id(source_id),
                    "notebook_id": ensure_record_id(notebook_id),
                },
            )
            cache[source_id] = bool(rows)
        return cache[source_id]

    return check


def make_cached_source_resolver() -> (
    Callable[[SourceAnnotation], Awaitable[Optional[Source]]]
):
    """Per-annotation source fetch for notebook chat, cached per request.

    Unlike source chat (one Source given), a notebook tag-ask may span sources,
    so each annotation's ``Source`` is fetched here (for ``parse_generation`` +
    the block window). Missing sources degrade to ``None`` (quote-only ref)."""
    cache: dict[str, Optional[Source]] = {}

    async def resolve(annotation: SourceAnnotation) -> Optional[Source]:
        source_id = str(annotation.source) if annotation.source else None
        if not source_id:
            return None
        if source_id not in cache:
            try:
                cache[source_id] = await Source.get(source_id)
            except NotFoundError:
                cache[source_id] = None
        return cache[source_id]

    return resolve
