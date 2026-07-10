from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from api.models import (
    AnnotationResponse,
    CreateAnnotationRequest,
    UpdateAnnotationRequest,
)
from api.routers._helpers import ensure_prefix
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Source, SourceAnnotation
from open_notebook.exceptions import NotFoundError
from open_notebook.utils.block_anchor import (
    ReaderAnchorError,
    derive_reader_anchor,
    resolve_anchor,
)

router = APIRouter()


# --- Reverse lookup: citing sessions + counts (cross-interface-study B2) -----
# Powers the "linked chats" view (Decisions #3): a highlight popover listing
# which chat sessions cited it, and a bulk per-source count for sidebar
# badges. Both are read-only and reuse the `cites_annotation` edge (migration
# 24, write-only until now) + `refers_to` (session scope classification, see
# `domain/notebook.py: ChatSession.get_notebook_id`).


class CitingSessionResponse(BaseModel):
    session_id: str
    title: str
    scope: str  # "notebook" | "source"
    notebook_id: Optional[str] = None
    source_id: Optional[str] = None
    updated: Optional[str] = None


class CitingCountsResponse(BaseModel):
    counts: Dict[str, int]


def _classify_citing_sessions(
    session_rows: List[Dict[str, Any]],
    refers_rows: List[Dict[str, Any]],
) -> List[CitingSessionResponse]:
    """Join session rows with their `refers_to` scope edge and classify.

    Pure (no DB) so it's directly testable with fake rows. `refers_rows` is
    `{in, out}` from `refers_to`; `out` is a full record id (`notebook:...` or
    `source:...`).

    Q-orphan-sessions: a citing session with no `refers_to` edge (its target
    notebook/source was deleted, or the edge is otherwise missing — shouldn't
    happen in steady state) is SKIPPED rather than surfaced with a best-effort
    "unknown" scope. Chosen as the simpler option: the response type stays a
    strict `"notebook"|"source"` union and no consumer needs to handle a third
    scope value for an edge case with no clear navigation target anyway.
    """
    scope_out_by_session: Dict[str, str] = {
        str(row["in"]): str(row["out"])
        for row in refers_rows
        if row.get("in") is not None and row.get("out") is not None
    }
    items: List[CitingSessionResponse] = []
    for row in session_rows:
        session_id = str(row.get("id"))
        out = scope_out_by_session.get(session_id)
        if out is None:
            continue
        if out.startswith("notebook:"):
            scope, notebook_id, source_id = "notebook", out, None
        elif out.startswith("source:"):
            scope, notebook_id, source_id = "source", None, out
        else:
            continue
        updated = row.get("updated")
        items.append(
            CitingSessionResponse(
                session_id=session_id,
                title=row.get("title") or "Untitled Session",
                scope=scope,
                notebook_id=notebook_id,
                source_id=source_id,
                updated=str(updated) if updated else None,
            )
        )
    items.sort(key=lambda item: item.updated or "", reverse=True)
    return items


def _anchor_state(
    annotation: SourceAnnotation, parse_generation: Optional[int]
) -> str:
    """Derive annotation staleness (db-design §2.3 — never stored).

    No ``block_seq`` → ``legacy`` (rect/quote-only); anchored against a stale
    generation → ``stale``; otherwise ``anchored``."""
    if annotation.block_seq is None:
        return "legacy"
    if annotation.anchor_gen != parse_generation:
        return "stale"
    return "anchored"


def _annotation_to_response(
    annotation: SourceAnnotation, parse_generation: Optional[int]
) -> AnnotationResponse:
    return AnnotationResponse(
        id=annotation.id or "",
        source_id=str(annotation.source) if annotation.source else "",
        page=annotation.page,
        rect=annotation.rect,
        color=annotation.color,
        note=annotation.note,
        quote=annotation.quote,
        tags=annotation.tags,
        block_seq=annotation.block_seq,
        block_end_seq=annotation.block_end_seq,
        anchor_start=annotation.anchor_start,
        anchor_end=annotation.anchor_end,
        anchor_gen=annotation.anchor_gen,
        anchor_state=_anchor_state(annotation, parse_generation),
        created=str(annotation.created),
        updated=str(annotation.updated),
    )


@router.get("/sources/{source_id}/annotations", response_model=List[AnnotationResponse])
async def get_source_annotations(source_id: str):
    """List all PDF highlight annotations for a source, oldest first."""
    try:
        source = await Source.get_meta(source_id)

        annotations = await SourceAnnotation.get_for_source(source_id)
        return [
            _annotation_to_response(a, source.parse_generation) for a in annotations
        ]
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    except Exception as e:
        logger.error(f"Error fetching annotations for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching annotations: {str(e)}")


@router.post(
    "/sources/{source_id}/annotations",
    response_model=AnnotationResponse,
    status_code=201,
)
async def create_source_annotation(source_id: str, request: CreateAnnotationRequest):
    """Create a highlight annotation for a source (db-design §2.3, Track D1/D7).

    Two create directions share the columns and branch on whether the client
    sent block fields:

    * **PDF-born** (rect+quote): the server RESOLVES the block anchor from the
      rect against the current parse generation; an un-parsed source stores a
      legacy rect/quote-only annotation.
    * **reader-born** (block range + offsets + quote): the server validates the
      range against the current generation and DERIVES the render rect from the
      blocks' bboxes so the highlight also paints on the PDF tab (409 when the
      source has no parsed generation, 404 when the range is stale/missing).
    """
    try:
        source = await Source.get_meta(source_id)

        if request.block_seq is not None:
            # Reader-born (D7): derive page + rect from the block range.
            anchor = await derive_reader_anchor(
                source,
                request.block_seq,
                request.block_end_seq
                if request.block_end_seq is not None
                else request.block_seq,
                request.anchor_start,
                request.anchor_end,
                request.quote,
            )
            annotation = SourceAnnotation(
                source=source_id,
                page=anchor.page,
                rect=anchor.rect,
                color=request.color,
                note=request.note,
                quote=request.quote,
                tags=request.tags,
                block_seq=anchor.block_seq,
                block_end_seq=anchor.block_end_seq,
                anchor_start=anchor.anchor_start,
                anchor_end=anchor.anchor_end,
                anchor_gen=anchor.anchor_gen,
                quote_hash=anchor.quote_hash,
            )
            await annotation.save()
            return _annotation_to_response(annotation, source.parse_generation)

        # PDF-born (D1): server resolves the anchor from rect + quote.
        annotation = SourceAnnotation(
            source=source_id,
            page=request.page,
            rect=[r.model_dump() for r in request.rect],
            color=request.color,
            note=request.note,
            quote=request.quote,
            tags=request.tags,
        )

        anchor = await resolve_anchor(
            source, [r.model_dump() for r in request.rect], request.quote
        )
        if anchor is not None:
            annotation.block_seq = anchor.block_seq
            annotation.block_end_seq = anchor.block_end_seq
            annotation.anchor_start = anchor.anchor_start
            annotation.anchor_end = anchor.anchor_end
            annotation.anchor_gen = anchor.anchor_gen
            annotation.quote_hash = anchor.quote_hash

        await annotation.save()
        return _annotation_to_response(annotation, source.parse_generation)
    except ReaderAnchorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    except Exception as e:
        logger.error(f"Error creating annotation for source {source_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating annotation: {str(e)}")


@router.patch("/annotations/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(annotation_id: str, request: UpdateAnnotationRequest):
    """Update an annotation's note, color and/or tags. Anchors are immutable."""
    try:
        annotation = await SourceAnnotation.get(annotation_id)

        if request.note is not None:
            annotation.note = request.note
        if request.color is not None:
            annotation.color = request.color
        if request.tags is not None:
            annotation.tags = request.tags

        await annotation.save()

        # Fetch the source's current generation only for the derived anchor_state.
        parse_generation: Optional[int] = None
        if annotation.source:
            try:
                source = await Source.get_meta(str(annotation.source))
                parse_generation = source.parse_generation
            except NotFoundError:
                parse_generation = None
        return _annotation_to_response(annotation, parse_generation)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Annotation not found")
    except Exception as e:
        logger.error(f"Error updating annotation {annotation_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating annotation: {str(e)}")


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str):
    """Delete an annotation."""
    try:
        annotation = await SourceAnnotation.get(annotation_id)
        await annotation.delete()

        return {"message": "Annotation deleted successfully"}
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Annotation not found")
    except Exception as e:
        logger.error(f"Error deleting annotation {annotation_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting annotation: {str(e)}")


@router.get(
    "/annotations/{annotation_id}/citing-sessions",
    response_model=List[CitingSessionResponse],
)
async def get_citing_sessions(annotation_id: str):
    """List chat sessions that cite this annotation, newest first (linked-chats view, B2).

    Read-only reverse lookup over the write-only `cites_annotation` edge
    (migration 24). An unknown/never-cited annotation id simply yields `[]` —
    no 404, since this is a bulk-lookup surface, not a single-resource fetch.
    """
    try:
        full_id = ensure_prefix(annotation_id, "source_annotation")
        edges = await repo_query(
            "SELECT in FROM cites_annotation WHERE out = $ann",
            {"ann": ensure_record_id(full_id)},
        )
        session_ids = [str(e["in"]) for e in edges if e.get("in") is not None]
        if not session_ids:
            return []

        rid_list = [ensure_record_id(sid) for sid in session_ids]
        session_rows = await repo_query(
            "SELECT id, title, updated FROM chat_session WHERE id IN $ids",
            {"ids": rid_list},
        )
        refers_rows = await repo_query(
            "SELECT in, out FROM refers_to WHERE in IN $ids",
            {"ids": rid_list},
        )
        return _classify_citing_sessions(session_rows, refers_rows)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching citing sessions for annotation {annotation_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Error fetching citing sessions: {str(e)}"
        )


@router.get(
    "/sources/{source_id}/annotations/citing-counts",
    response_model=CitingCountsResponse,
)
async def get_citing_counts(source_id: str):
    """Bulk citing-session count per annotation for a source (sidebar badges, B2).

    One extra query beyond the existing annotation-list fetch: annotation ids
    for the source, then a single grouped count over `cites_annotation`
    (mirrors `command_service`'s `count() AS n ... GROUP BY` usage) — avoids an
    N+1 per-annotation count.
    """
    try:
        full_source_id = ensure_prefix(source_id, "source")
        annotations = await SourceAnnotation.get_for_source(full_source_id)
        ann_ids = [ensure_record_id(a.id) for a in annotations if a.id]
        if not ann_ids:
            return CitingCountsResponse(counts={})

        rows = await repo_query(
            "SELECT out, count() AS n FROM cites_annotation WHERE out IN $ids GROUP BY out",
            {"ids": ann_ids},
        )
        counts = {str(r["out"]): int(r.get("n") or 0) for r in rows}
        return CitingCountsResponse(counts=counts)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching citing counts for source {source_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching citing counts: {str(e)}"
        )
