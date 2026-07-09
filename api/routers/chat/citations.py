import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from open_notebook.ai.context_windows import get_context_window
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import ChatMessageMedia

from api.routers.chat.schemas import (
    ChatMessage,
    Citation,
    MediaItem,
    ToolUseDisclosure,
    UsageInfo,
)

# Inline marker form: [source:id] / [note:id] / [source_insight:id], tolerating an
# optional #p=<n> page anchor (see pdf-viewer-citations plan). The literal type
# prefix matches the actual SurrealDB record ids returned by the search tool.
FOLLOWUPS_SENTINEL = "---FOLLOWUPS---"
_CITATION_PATTERN = re.compile(
    r"(source_insight|note|source):([a-zA-Z0-9_]+)(?:#p=(\d+))?"
)
_BULLET_PATTERN = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _make_snippet(text: Optional[str], limit: int = 160) -> Optional[str]:
    """Collapse whitespace and clip to a short preview snippet."""
    if not text:
        return None
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


# (title field, snippet field) per citation table. Only the title + a short
# snippet are ever surfaced, so we slice the snippet server-side instead of
# loading whole records (a source's full_text + page_map can be a whole book).
_CITATION_FIELDS: Dict[str, Tuple[str, str]] = {
    "source": ("title", "full_text"),
    "note": ("title", "content"),
    "source_insight": ("insight_type", "content"),
}


async def _fetch_citations_meta(
    ids_by_type: Dict[str, List[str]],
) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """Batch-resolve (title, snippet) for every cited record: ONE query per table.

    Replaces the former per-citation ``Source/Note/SourceInsight.get`` (each of
    which loaded the whole record — full_text, page_map — just to build a
    160-char snippet). Returns a per-request memo keyed by the citation's full id.
    Records that are missing or whose table query fails are simply absent, so the
    caller degrades to ``(None, None)`` exactly as before.
    """
    memo: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for ctype, ids in ids_by_type.items():
        fields = _CITATION_FIELDS.get(ctype)
        if not fields or not ids:
            continue
        title_field, snippet_field = fields
        # ?? '' guards a NONE snippet field so string::slice never errors
        # (Open Question Q-snippet-slice); slice 0..300 raw chars, then the
        # 160-char snippet rule below trims/collapses to the identical preview.
        query = (
            f"SELECT id, {title_field} AS title, "
            f"string::slice({snippet_field} ?? '', 0, 300) AS snippet FROM $ids"
        )
        record_ids = [ensure_record_id(i) for i in ids]
        # Map the canonical RecordID string back to the original marker id.
        by_key = {str(r): orig for r, orig in zip(record_ids, ids)}
        try:
            rows = await repo_query(query, {"ids": record_ids})
        except Exception as e:
            logger.warning(f"Could not resolve {ctype} citations: {str(e)}")
            continue
        for row in rows or []:
            rid = row.get("id")
            if rid is None:
                continue
            key = by_key.get(str(rid), str(rid))
            memo[key] = (row.get("title"), _make_snippet(row.get("snippet")))
    return memo


async def _resolve_citations(
    content: str,
) -> Tuple[str, List[Citation], List[str]]:
    """Parse inline citation markers + a trailing ---FOLLOWUPS--- block.

    Returns (clean_content, citations, followups). Inline markers are KEPT in
    clean_content for frontend back-compat; only the followups block is stripped.
    Citations are deduplicated and numbered by first appearance.
    """
    if not content:
        return content, [], []

    # Split off the followups block (everything after the sentinel)
    clean = content
    followups: List[str] = []
    if FOLLOWUPS_SENTINEL in content:
        head, _, tail = content.partition(FOLLOWUPS_SENTINEL)
        clean = head.rstrip()
        for line in tail.splitlines():
            stripped = _BULLET_PATTERN.sub("", line).strip()
            if stripped:
                followups.append(stripped)

    # First pass: number citations by first appearance (dedup on full id) and
    # group the distinct ids by type for a single batched metadata query each.
    seen: Dict[str, int] = {}
    ids_by_type: Dict[str, List[str]] = {}
    ordered: List[Tuple[str, str, Optional[str]]] = []
    for match in _CITATION_PATTERN.finditer(clean):
        ctype, cid, page = match.group(1), match.group(2), match.group(3)
        full_id = f"{ctype}:{cid}"
        if full_id in seen:
            continue
        seen[full_id] = len(seen) + 1
        ids_by_type.setdefault(ctype, []).append(full_id)
        ordered.append((ctype, full_id, page))

    # One query per cited table (per-request memo), then assemble the payload.
    meta = await _fetch_citations_meta(ids_by_type)

    citations: List[Citation] = []
    for ctype, full_id, page in ordered:
        title, snippet = meta.get(full_id, (None, None))
        citations.append(
            Citation(
                id=full_id,
                type=ctype,  # type: ignore[arg-type]
                number=seen[full_id],
                title=title,
                snippet=snippet,
                page=int(page) if page else None,
            )
        )

    return clean, citations, followups


async def _build_chat_message(msg: Any, fallback_index: int) -> ChatMessage:
    """Convert a LangChain message into a ChatMessage, resolving AI citations."""
    mtype = msg.type if hasattr(msg, "type") else "unknown"
    mcontent = msg.content if hasattr(msg, "content") else str(msg)
    msg_id = getattr(msg, "id", f"msg_{fallback_index}")

    if mtype == "ai" and isinstance(mcontent, str):
        clean, citations, followups = await _resolve_citations(mcontent)
    else:
        clean = mcontent if isinstance(mcontent, str) else str(mcontent)
        citations, followups = [], []

    # Tool-use disclosures + media attachments ride on the message's
    # additional_kwargs (tool_uses: Claude Agent path / AI only; media: the human
    # turn). Absent/empty on the other paths.
    extra = getattr(msg, "additional_kwargs", None) or {}
    raw_tool_uses = extra.get("tool_uses") if isinstance(extra, dict) else None
    tool_uses = (
        [ToolUseDisclosure(**t) for t in raw_tool_uses] if raw_tool_uses else None
    )
    raw_media = extra.get("media") if isinstance(extra, dict) else None
    media = [MediaItem(**m) for m in raw_media] if raw_media else []

    # Post-hoc thinking (A2): the graph node persists parsed <think> content on
    # additional_kwargs.thinking when the model produced any. Absent on
    # messages checkpointed before this change — degrade to None via .get().
    raw_thinking = extra.get("thinking") if isinstance(extra, dict) else None
    thinking = raw_thinking if isinstance(raw_thinking, str) and raw_thinking else None

    # Per-turn token usage (Claude Agent path only; Esperanto messages carry no
    # "usage" key → stays None → serializes as usage: null). The context window
    # is resolved server-side from the effective model id. Malformed payloads
    # must NEVER fail the session read — degrade to usage=None.
    usage: Optional[UsageInfo] = None
    raw_usage = extra.get("usage") if isinstance(extra, dict) else None
    if isinstance(raw_usage, dict):
        try:
            usage = UsageInfo(
                **raw_usage,
                context_window=get_context_window(raw_usage.get("model")),
            )
        except Exception as e:
            logger.debug(
                f"Ignoring malformed usage on message {msg_id}: {str(e)}"
            )
            usage = None

    # Hydrate a late-arriving illustration (auto-illustrate-chat, B5): merge the
    # chat_message_media sidecar row for this AI message, if one exists. Only
    # stable AI message ids (the "ai-" prefix assigned in graphs/chat.py) can
    # have a sidecar row. Never let a lookup/merge failure fail the session
    # read — degrade to the un-hydrated message.
    if mtype == "ai" and isinstance(msg_id, str) and msg_id.startswith("ai-"):
        try:
            sidecar = await ChatMessageMedia.get_for_message(msg_id)
            if sidecar is not None:
                if sidecar.mode == "image" and sidecar.media:
                    media.append(MediaItem(**sidecar.media))
                elif sidecar.mode == "diagram" and sidecar.diagram:
                    clean = f"{clean}\n\n```mermaid\n{sidecar.diagram}\n```"
        except Exception as e:
            logger.warning(f"Could not hydrate media for message {msg_id}: {str(e)}")

    return ChatMessage(
        id=msg_id,
        type=mtype,
        content=clean,
        timestamp=None,
        citations=citations,
        followups=followups,
        tool_uses=tool_uses,
        media=media,
        usage=usage,
        thinking=thinking,
    )
