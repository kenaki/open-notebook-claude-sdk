import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from open_notebook.domain.notebook import ChatMessageMedia, Note, Source, SourceInsight

from api.routers.chat.schemas import ChatMessage, Citation, MediaItem, ToolUseDisclosure

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


async def _fetch_citation_meta(
    ctype: str, full_id: str
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a (title, snippet) pair for a cited document, defensively."""
    try:
        if ctype == "source":
            src = await Source.get(full_id)
            if src:
                return src.title, _make_snippet(getattr(src, "full_text", None))
        elif ctype == "note":
            note = await Note.get(full_id)
            if note:
                return note.title, _make_snippet(getattr(note, "content", None))
        elif ctype == "source_insight":
            insight = await SourceInsight.get(full_id)
            if insight:
                return (
                    getattr(insight, "insight_type", None),
                    _make_snippet(getattr(insight, "content", None)),
                )
    except Exception as e:
        logger.warning(f"Could not resolve citation {full_id}: {str(e)}")
    return None, None


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

    # Extract + number citations by first appearance (dedup on full id)
    citations: List[Citation] = []
    seen: Dict[str, int] = {}
    for match in _CITATION_PATTERN.finditer(clean):
        ctype, cid, page = match.group(1), match.group(2), match.group(3)
        full_id = f"{ctype}:{cid}"
        if full_id in seen:
            continue
        number = len(seen) + 1
        seen[full_id] = number
        title, snippet = await _fetch_citation_meta(ctype, full_id)
        citations.append(
            Citation(
                id=full_id,
                type=ctype,  # type: ignore[arg-type]
                number=number,
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
    )
