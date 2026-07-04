"""Chat-illustration enrichment (auto-illustrate-chat, chunk W1).

Given a completed AI chat message, decide — via a two-stage gate — whether a
visual would genuinely help, and for the **diagram** path generate one strict
Mermaid block from the local qwen3.6 model and persist it to the
``chat_message_media`` sidecar (upsert on ``message_id``). The API's session read
hydrates the sidecar back into the message (B5).

Design contracts (see ``.claude/plans/chat-foundation/coordinator.md``):
- **D6 / Q-modelid:** ALL enrichment LLM steps reuse the already-registered local
  **qwen3.6** language model, resolved at runtime (a lookup, not a fork). The chat
  turn's model is ignored (it may be a cloud model or the Claude Agent sentinel).
- **P-6 heavy lane:** every LLM call acquires the process-wide ``heavy_lane`` when
  ``is_heavy_model`` is true (qwen3.6 is local/heavy), so enrichment serializes
  BEHIND interactive chat turns on the single GPU instead of contending.
- **Never raise:** enrichment is background progressive-enhancement in a separate
  worker process. Any failure (load, gate, generation, DB) resolves to
  ``mode='none'`` — it must never crash the worker loudly or fail the chat turn.
- **B7 S-gate (GO-WITH-ADJUSTMENTS):** gate fires only at confidence ≥ τ (0.6).
- qwen3.6 is a THINKING model — strip ``<think>`` via ``clean_thinking_content``
  and set ``max_tokens`` explicitly (unset → truncated/garbled JSON, B7 lesson).

W2 (this chunk) builds the candidate→judge HALF of the image pipeline: query
expansion → search (Wikipedia PageImages first, with early-exit; else Wikimedia
Commons + Openverse) → qwen3.6 VLM relevance judge with **abstain** (rank +
threshold at τ, top-K candidates). It hands the chosen external URL to the W3
seam ``_fetch_and_store_image`` — which in W2 is a STUB that logs and returns
``None``, so the image path still resolves to ``mode='none'`` (no bytes fetched
for storage, no ``mode='image'`` sidecar). W3 replaces the stub body with the
safety judge (fail-closed) + SSRF-guarded fetch → WebP → store → ``mode='image'``
sidecar; the branch already writes ``mode='image'`` the moment the stub returns a
``MediaItem`` dict.
"""

import asyncio
import base64
import json
import re
from typing import Optional

import httpx
from ai_prompter import Prompter
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from open_notebook.ai.models import DefaultModels
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.database.repository import repo_query
from open_notebook.domain.notebook import ChatMessageMedia
from open_notebook.graphs.chat import graph as chat_graph
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content

# B7 S-gate (GO-WITH-ADJUSTMENTS): only illustrate at confidence ≥ τ.
GATE_CONFIDENCE_THRESHOLD = 0.6

# The registered local model reused for every enrichment step (D6). Resolved to
# its record id at runtime; these are the fallbacks if the direct lookup misses.
_QWEN_PROVIDER = "ollama"
_QWEN_NAME = "qwen3.6:35b"

# Token budgets. qwen3.6 is a thinking model and does NOT honour ``/no_think``,
# so the <think> block (stripped by clean_thinking_content) eats the budget
# BEFORE the JSON is emitted. Empirically, 1024 (the plan's guess) yields an
# EMPTY post-think output on real-length replies → the gate degrades to none and
# under-fires; 2048 leaves room for the reasoning + the small JSON verdict on a
# 4000-char-truncated message. Diagram generation needs the most room.
_GATE_MAX_TOKENS = 2048
_DIAGRAM_MAX_TOKENS = 8192

# Cheap prefilter: skip obviously-not-illustratable replies before spending GPU.
_MIN_CONTENT_CHARS = 120
_GREETING_RE = re.compile(
    r"^(hi|hey|hello|thanks|thank you|yes|no|ok|okay|sure|got it|good|great|nice|"
    r"you're welcome|no problem)\b",
    re.IGNORECASE,
)

# Diagram extraction / sanity.
_MERMAID_FENCE_RE = re.compile(r"```mermaid\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_MERMAID_KEYWORDS = ("graph ", "graph\n", "flowchart", "sequencediagram", "erdiagram")

# ---- Image pipeline (W2) --------------------------------------------------
# B7 S-gate adjustments (GO-WITH-ADJUSTMENTS): τ=0.6 (GATE_CONFIDENCE_THRESHOLD
# above is reused as the relevance τ), top-K=3, PageImages-first with early-exit.
_TOP_K = 3  # hard cap on VLM relevance-judge calls per illustration.

# Token budgets (mirror the B7 spike's proven values; qwen3.6 is a thinking
# model, so the <think> block eats budget before the JSON — keep generous).
_EXPAND_MAX_TOKENS = 2048
_JUDGE_MAX_TOKENS = 3072

# No-key search sources (D4). Wikimedia policy REQUIRES a descriptive
# User-Agent; Openverse recommends one.
_USER_AGENT = (
    "OpenNotebook/dev (self-hosted research assistant; "
    "+https://github.com/lfnovo/open-notebook)"
)
_WP_API = "https://en.wikipedia.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_OPENVERSE_API = "https://api.openverse.org/v1/images/"
_SEARCH_TIMEOUT = 15.0

# The relevance judge needs the raw image bytes as a data-URI (Ollama's vision
# path does not fetch remote URLs itself). This is a THROWAWAY fetch of a
# search-API-returned image host (Wikimedia/Openverse) purely to feed the VLM —
# NOT the storage fetch (W3 owns the SSRF-guarded, byte-capped, re-encoded store
# fetch). Hard-capped + timed out so it can never hang or blow up memory.
_JUDGE_FETCH_TIMEOUT = 20.0
_JUDGE_FETCH_MAX_BYTES = 10_000_000  # 10 MB

# The :11435 heavy-slot admission gate returns 503 while ds4/gpt-oss swaps out or
# qwen3.6 is loading. heavy_lane serializes OUR jobs but not the co-tenant ds4,
# so a transient gate 503 can still hit mid-transition — back off and retry
# rather than degrade a whole illustration to abstain (B7 spike lesson).
_GATE_RETRY_MAX_ATTEMPTS = 6
_GATE_RETRY_BASE_DELAY = 3.0
_GATE_RETRY_MAX_DELAY = 25.0
_GATE_RETRY_SIGNATURES = (
    "model transition",
    "ollama_gate",
    "retry shortly",
    "503",
    "loading",
)


def _prefixed(value: str, table: str) -> str:
    return value if value.startswith(f"{table}:") else f"{table}:{value}"


def _extract_json_object(text: str) -> Optional[dict]:
    """Extract the first balanced ``{...}`` JSON object from ``text``.

    Robust to a thinking-model preamble or trailing prose around the object.
    Returns ``None`` if no parseable object is found.
    """
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None


def _sanitize_mermaid(body: Optional[str]) -> Optional[str]:
    """Minimal server-side sanity check on a Mermaid source (F4 does the strict
    render + DOMPurify + parse-or-fallback client-side).

    Drops ``click`` directives, rejects HTML/script, and requires a known diagram
    keyword. Returns the cleaned source or ``None`` if it is not plausibly a
    supported diagram.
    """
    if not body or not body.strip():
        return None
    lines = [
        ln for ln in body.splitlines() if not ln.strip().lower().startswith("click ")
    ]
    cleaned = "\n".join(lines).strip()
    if not cleaned:
        return None
    low = cleaned.lower()
    if "<script" in low or "javascript:" in low:
        return None
    if not any(kw in low for kw in _MERMAID_KEYWORDS):
        return None
    return cleaned


async def _resolve_illustration_model_id(input_model_id: Optional[str]) -> Optional[str]:
    """Resolve the local qwen3.6 record id for enrichment (D6 / Q-modelid).

    Prefers a direct ``model`` table lookup, then the DefaultModels slots that the
    Ollama registration repoints at qwen3.6 (tools / large-context / transformation),
    and only as a last resort falls back to the chat turn's own model id. A lookup,
    not a fork.
    """
    try:
        rows = await repo_query(
            "SELECT id FROM model WHERE provider = $p AND type = 'language' "
            "AND name = $n LIMIT 1",
            {"p": _QWEN_PROVIDER, "n": _QWEN_NAME},
        )
        if rows:
            return str(rows[0]["id"])
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"illustrate: qwen3.6 model lookup failed: {e}")

    try:
        defaults = await DefaultModels.get_instance()
        for slot in (
            defaults.default_tools_model,
            defaults.large_context_model,
            defaults.default_transformation_model,
        ):
            if slot:
                return slot
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"illustrate: DefaultModels lookup failed: {e}")

    return input_model_id


async def _invoke_with_gate_retry(model, payload):
    """Run one blocking ``model.invoke(payload)`` off the event loop, retrying the
    :11435 heavy-slot admission gate's transient 503 with capped backoff.

    Only the gate's known transient signatures are retried; every other error
    propagates immediately (the callers turn it into a graceful abstain/none).
    """
    delay = _GATE_RETRY_BASE_DELAY
    last_exc: Optional[Exception] = None
    for attempt in range(_GATE_RETRY_MAX_ATTEMPTS):
        try:
            return await asyncio.to_thread(model.invoke, payload)
        except Exception as e:  # noqa: BLE001 - inspected below
            last_exc = e
            msg = str(e).lower()
            if not any(sig in msg for sig in _GATE_RETRY_SIGNATURES):
                raise
            if attempt < _GATE_RETRY_MAX_ATTEMPTS - 1:
                logger.info(
                    f"illustrate: heavy-slot gate busy (attempt {attempt + 1}), "
                    f"backing off {delay:.0f}s"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 1.6, _GATE_RETRY_MAX_DELAY)
    assert last_exc is not None
    raise last_exc


async def _invoke_llm(model_id: Optional[str], prompt: str, max_tokens: int) -> str:
    """Provision qwen3.6 and run one blocking text invoke off the event loop.

    Acquires ``heavy_lane`` when the model is local/heavy (P-6). Strips
    ``<think>`` blocks from the response (qwen3.6 is a thinking model).
    """
    # Imported lazily: ``graphs`` → ``commands`` is the reverse of the usual
    # dependency direction, and a module-level import here creates a cycle
    # (commands/__init__ imports illustrate_commands, which imports this module).
    from commands._heavy_lane import heavy_lane, is_heavy_model

    model = await provision_langchain_model(prompt, model_id, "chat", max_tokens=max_tokens)

    if await is_heavy_model(model_id):
        async with heavy_lane:
            logger.debug(f"illustrate acquired heavy lane (model={model_id!r})")
            message = await _invoke_with_gate_retry(model, prompt)
    else:
        message = await _invoke_with_gate_retry(model, prompt)

    content = message.content if hasattr(message, "content") else message
    return clean_thinking_content(extract_text_content(content))


async def _invoke_vlm(
    model_id: Optional[str], prompt: str, data_uri: str, max_tokens: int
) -> str:
    """Vision variant of ``_invoke_llm``: one qwen3.6 invoke with a text block +
    an ``image_url`` data-URI block (the same shape ``graphs.chat`` builds via
    ``_attach_media_blocks``). Same heavy-lane + think-strip + gate-retry posture.
    """
    from commands._heavy_lane import heavy_lane, is_heavy_model

    # Token-count provisioning only sees the text prompt (the image bytes are not
    # tokenized here); that is fine — enrichment always resolves to local qwen3.6.
    model = await provision_langchain_model(prompt, model_id, "chat", max_tokens=max_tokens)
    payload = [
        HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]
        )
    ]

    if await is_heavy_model(model_id):
        async with heavy_lane:
            logger.debug(f"illustrate VLM acquired heavy lane (model={model_id!r})")
            message = await _invoke_with_gate_retry(model, payload)
    else:
        message = await _invoke_with_gate_retry(model, payload)

    content = message.content if hasattr(message, "content") else message
    return clean_thinking_content(extract_text_content(content))


async def _load_message_content(
    full_session_id: str, message_id: str
) -> Optional[str]:
    """Read one AI message's text by id from the chat LangGraph checkpoint.

    Q-B-msgload default: ``chat_graph.get_state(thread_id=session_id)`` then match
    on ``.id``. The worker is the checkpoint's sole writer; this is a plain read.
    """
    state = await asyncio.to_thread(
        chat_graph.get_state,
        RunnableConfig(configurable={"thread_id": full_session_id}),
    )
    values = getattr(state, "values", None) or {}
    for msg in values.get("messages", []) or []:
        if getattr(msg, "id", None) == message_id:
            return extract_text_content(getattr(msg, "content", "") or "")
    return None


def _cheap_prefilter_skip(content: str) -> bool:
    """Stage-1 gate: cheap heuristic to skip obviously non-illustratable replies
    without spending a GPU call. Bias toward skipping only clear cases; the LLM
    gate is the real filter."""
    text = (content or "").strip()
    if len(text) < _MIN_CONTENT_CHARS:
        return True
    if _GREETING_RE.match(text) and len(text) < 400:
        return True
    return False


async def _run_gate(content: str, model_id: Optional[str]) -> dict:
    """Stage-2 gate: constrained qwen3.6 JSON decision. Bias hard toward none —
    any failure degrades to a 'none' decision."""
    try:
        prompt = Prompter(prompt_template="illustrate/gate").render(
            data={"content": content[:4000]}
        )
        raw = await _invoke_llm(model_id, prompt, _GATE_MAX_TOKENS)
        decision = _extract_json_object(raw)
        if not isinstance(decision, dict):
            logger.info("illustrate gate: no parseable JSON → none")
            return {"illustrate": False, "mode": "none", "confidence": 0.0, "subject": ""}
        return decision
    except Exception as e:
        try:
            _, msg = classify_error(e)
        except Exception:
            msg = str(e)
        logger.warning(f"illustrate gate failed → none: {msg}")
        return {"illustrate": False, "mode": "none", "confidence": 0.0, "subject": ""}


async def _generate_diagram(
    content: str, subject: str, model_id: Optional[str]
) -> Optional[str]:
    """Prompt qwen3.6 for ONE strict Mermaid block; return the sanitized source
    or ``None``."""
    try:
        prompt = Prompter(prompt_template="illustrate/diagram").render(
            data={"content": content[:6000], "subject": subject or ""}
        )
        raw = await _invoke_llm(model_id, prompt, _DIAGRAM_MAX_TOKENS)
        match = _MERMAID_FENCE_RE.search(raw)
        body = match.group(1) if match else raw
        return _sanitize_mermaid(body)
    except Exception as e:
        try:
            _, msg = classify_error(e)
        except Exception:
            msg = str(e)
        logger.warning(f"illustrate diagram generation failed → none: {msg}")
        return None


async def _write_sidecar(
    message_id: str,
    session_id: str,
    mode: str,
    diagram: Optional[str] = None,
    media: Optional[dict] = None,
) -> None:
    """Upsert the ``chat_message_media`` sidecar row (UNIQUE index on
    ``message_id`` — update in place if a row already exists)."""
    try:
        existing = await ChatMessageMedia.get_for_message(message_id)
        if existing is not None:
            existing.mode = mode
            existing.diagram = diagram
            existing.media = media
            await existing.save()
        else:
            await ChatMessageMedia(
                message_id=message_id,
                session_id=session_id,
                mode=mode,
                diagram=diagram,
                media=media,
            ).save()
    except Exception as e:
        logger.warning(f"illustrate: sidecar write failed for {message_id}: {e}")


# ===========================================================================
# Image pipeline (W2): expand → search (PageImages-first) → VLM relevance/abstain
# ===========================================================================


async def _expand_query(
    subject: str, content: str, model_id: Optional[str]
) -> list[str]:
    """qwen3.6 turns the gate's ``subject`` into 1-3 concrete visual search terms.

    Never raises — on any failure returns ``[subject]`` so the search stage still
    has a query to run.
    """
    try:
        prompt = Prompter(prompt_template="illustrate/expand").render(
            data={"subject": subject, "content": (content or "")[:600]}
        )
        raw = await _invoke_llm(model_id, prompt, _EXPAND_MAX_TOKENS)
        obj = _extract_json_object(raw) or {}
        terms = [
            t.strip()
            for t in (obj.get("terms") or [])
            if isinstance(t, str) and t.strip()
        ][:3]
        return terms or [subject]
    except Exception as e:
        try:
            _, msg = classify_error(e)
        except Exception:
            msg = str(e)
        logger.warning(f"illustrate expand failed → using subject verbatim: {msg}")
        return [subject]


async def _search_wikipedia_pageimage(query: str) -> list[dict]:
    """Wikipedia PageImages — the canonical lead image for the best-matching
    article (D4's 'abstract shortcut': one representative image per concept)."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrlimit": 3, "gsrnamespace": 0,
        "prop": "pageimages", "piprop": "thumbnail|name", "pithumbsize": 800,
    }
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_SEARCH_TIMEOUT,
        ) as client:
            r = await client.get(_WP_API, params=params)
            r.raise_for_status()
            pages = (r.json().get("query", {}) or {}).get("pages", {}) or {}
            for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
                thumb = p.get("thumbnail", {}) or {}
                if thumb.get("source"):
                    out.append({
                        "source": "wikipedia_pageimage",
                        "url": thumb["source"],
                        "title": p.get("title", ""),
                    })
    except Exception as e:
        logger.info(f"illustrate search: PageImages failed for {query!r}: {type(e).__name__}")
    return out


async def _search_commons(query: str, limit: int = 4) -> list[dict]:
    """Wikimedia Commons file search (namespace 6)."""
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|mime|size", "iiurlwidth": 800,
    }
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_SEARCH_TIMEOUT,
        ) as client:
            r = await client.get(_COMMONS_API, params=params)
            r.raise_for_status()
            pages = (r.json().get("query", {}) or {}).get("pages", {}) or {}
            for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
                ii = (p.get("imageinfo") or [{}])[0]
                if not (ii.get("mime", "") or "").startswith("image/"):
                    continue  # skip pdf/svg-as-doc/video
                url = ii.get("thumburl") or ii.get("url")
                if url:
                    out.append({
                        "source": "commons",
                        "url": url,
                        "title": p.get("title", ""),
                    })
    except Exception as e:
        logger.info(f"illustrate search: Commons failed for {query!r}: {type(e).__name__}")
    return out


async def _search_openverse(query: str, limit: int = 4) -> list[dict]:
    """Openverse CC/PD image API. No key; descriptive UA recommended."""
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_SEARCH_TIMEOUT,
        ) as client:
            r = await client.get(_OPENVERSE_API, params={"q": query, "page_size": limit})
            r.raise_for_status()
            for it in r.json().get("results", []) or []:
                url = it.get("thumbnail") or it.get("url")
                if url:
                    out.append({
                        "source": "openverse",
                        "url": url,
                        "title": it.get("title", "") or "",
                    })
    except Exception as e:
        logger.info(f"illustrate search: Openverse failed for {query!r}: {type(e).__name__}")
    return out


async def _fetch_image_data_uri(url: str) -> Optional[str]:
    """Download an image (from a search-API host) as a base64 ``data:`` URI to
    feed the VLM judge. Streamed with a HARD byte cap (never trusts
    Content-Length) and a timeout. Returns ``None`` on any failure / oversize.

    NOTE: this is the judge-only fetch. W3 owns the SSRF-guarded, re-encoded
    STORAGE fetch; this fetch only ever targets the URLs the search APIs returned.
    """
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_JUDGE_FETCH_TIMEOUT,
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > _JUDGE_FETCH_MAX_BYTES:
                        logger.info(
                            f"illustrate judge-fetch: {url[:60]} exceeds "
                            f"{_JUDGE_FETCH_MAX_BYTES} byte cap → skip"
                        )
                        return None
                mime = (resp.headers.get("content-type", "image/jpeg") or "").split(";")[0].strip()
                if not mime.startswith("image/"):
                    mime = "image/jpeg"
        b64 = base64.b64encode(bytes(buf)).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.info(f"illustrate judge-fetch failed for {url[:60]}: {type(e).__name__}")
        return None


async def _judge_candidate(
    candidate: dict, subject: str, context: str, model_id: Optional[str]
) -> dict:
    """Fetch a candidate's bytes and ask qwen3.6 whether the image is a relevant
    illustration of ``subject``. Returns the candidate dict enriched with
    ``relevant``/``confidence``/``reason``/``skipped``. Never raises."""
    result = {**candidate, "relevant": False, "confidence": 0.0, "reason": "", "skipped": True}
    try:
        data_uri = await _fetch_image_data_uri(candidate["url"])
        if not data_uri:
            return result
        prompt = Prompter(prompt_template="illustrate/relevance").render(
            data={"subject": subject, "context": (context or "")[:600]}
        )
        raw = await _invoke_vlm(model_id, prompt, data_uri, _JUDGE_MAX_TOKENS)
        verdict = _extract_json_object(raw) or {}
        try:
            confidence = float(verdict.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        result.update({
            "relevant": bool(verdict.get("relevant")),
            "confidence": confidence,
            "reason": str(verdict.get("reason") or "")[:80],
            "skipped": False,
        })
    except Exception as e:
        try:
            _, msg = classify_error(e)
        except Exception:
            msg = str(e)
        logger.info(f"illustrate judge failed for {candidate.get('url', '')[:60]}: {msg}")
    return result


def _pick_winner(judged: list[dict]) -> Optional[dict]:
    """Rank + threshold with abstain: the highest-confidence relevant candidate
    that clears τ, or ``None`` (abstain)."""
    winners = [
        j for j in judged
        if not j.get("skipped")
        and j.get("relevant")
        and j.get("confidence", 0.0) >= GATE_CONFIDENCE_THRESHOLD
    ]
    winners.sort(key=lambda j: j.get("confidence", 0.0), reverse=True)
    return winners[0] if winners else None


async def _judge_pool(
    pool: list[dict],
    subject: str,
    context: str,
    model_id: Optional[str],
    seen_urls: set,
    budget: int,
) -> list[dict]:
    """Judge up to ``budget`` not-yet-seen candidates from ``pool`` (in order).
    Only successfully-judged candidates count against the budget (a fetch failure
    doesn't burn a slot). Bounds total VLM calls."""
    judged: list[dict] = []
    for cand in pool:
        if len([j for j in judged if not j.get("skipped")]) >= budget:
            break
        url = cand.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        verdict = await _judge_candidate(cand, subject, context, model_id)
        judged.append(verdict)
        logger.info(
            f"illustrate judge [{verdict.get('source')}] relevant="
            f"{verdict.get('relevant')} conf={verdict.get('confidence'):.2f} "
            f"skipped={verdict.get('skipped')} :: {verdict.get('title', '')[:50]!r} "
            f"{verdict.get('reason', '')!r}"
        )
    return judged


async def _fetch_and_store_image(
    candidate: dict,
    subject: str,
    message_id: str,
    session_id: str,
    model_id: Optional[str],
) -> Optional[dict]:
    """W3 SEAM — turn the chosen candidate into a stored, safe ``MediaItem`` dict.

    **W2 stub:** logs the chosen URL and returns ``None`` (→ the image path
    abstains, writes ``mode='none'``). No bytes are fetched for storage and no
    ``mode='image'`` sidecar is written in W2.

    **W3 fills this in** with, in order: qwen3.6-VL safety judge (fail-closed —
    unsafe / error / timeout → return ``None``); SSRF-guarded, byte-capped,
    redirect-revalidating fetch of ``candidate['url']``; Pillow decode →
    re-encode to WebP (strips EXIF); hash-dedupe store under ``CHAT_MEDIA_FOLDER``;
    then RETURN the ``MediaItem`` dict
    ``{"type": "image", "url": "/api/chat/media/<hash>.webp",
       "label": candidate.get("title") or subject}``.
    Returning that dict makes the caller write the ``mode='image'`` sidecar.

    Params it will need are all here: the chosen ``candidate`` (``url``/``title``/
    ``source``/``confidence``), the ``subject`` (MediaItem label fallback),
    ``message_id``/``session_id`` (sidecar keys), and ``model_id`` (the resolved
    qwen3.6 for the safety judge — pass to ``_invoke_vlm``).
    """
    logger.info(
        f"illustrate: chosen image for {message_id} → "
        f"url={candidate.get('url')!r} source={candidate.get('source')!r} "
        f"conf={candidate.get('confidence')} title={candidate.get('title', '')[:60]!r}; "
        f"W3 safety+fetch+store not built → abstaining (mode='none')"
    )
    return None


async def _finish_image(
    winner: dict,
    subject: str,
    message_id: str,
    session_id: str,
    model_id: Optional[str],
) -> str:
    """Hand the chosen candidate to the W3 seam; write ``mode='image'`` if it
    returns a stored MediaItem, else abstain (``mode='none'``)."""
    media = await _fetch_and_store_image(winner, subject, message_id, session_id, model_id)
    if not media:
        await _write_sidecar(message_id, session_id, mode="none")
        return "none"
    await _write_sidecar(message_id, session_id, mode="image", media=media)
    logger.info(f"illustrate: wrote image sidecar for {message_id}")
    return "image"


async def _run_image_pipeline(
    subject: str,
    content: str,
    message_id: str,
    session_id: str,
    model_id: Optional[str],
) -> str:
    """Candidate→judge half of the image path (W2). Returns the final mode
    ('image' | 'none'). Never raises."""
    try:
        terms = await _expand_query(subject, content, model_id)
        primary = terms[0] if terms else subject
        logger.info(f"illustrate image: subject={subject!r} expansion={terms}")

        seen_urls: set = set()

        # Stage A — Wikipedia PageImages first, with EARLY-EXIT (B7: won 4/5).
        # If a canonical PageImages candidate clears τ, we never touch Commons /
        # Openverse — saving both search round-trips and VLM judge calls.
        page_pool = await _search_wikipedia_pageimage(subject)
        logger.info(f"illustrate image: PageImages returned {len(page_pool)} candidate(s)")
        page_judged = await _judge_pool(
            page_pool, subject, content, model_id, seen_urls, budget=_TOP_K
        )
        winner = _pick_winner(page_judged)
        if winner is not None:
            logger.info(
                f"illustrate image: PageImages EARLY-EXIT fired for {message_id} "
                f"(conf={winner.get('confidence'):.2f})"
            )
            return await _finish_image(winner, subject, message_id, session_id, model_id)

        # Stage B — Commons + Openverse (only reached if PageImages didn't win).
        # Total VLM judge calls stay capped at top-K across both stages.
        remaining = _TOP_K - len([j for j in page_judged if not j.get("skipped")])
        all_judged = list(page_judged)
        if remaining > 0:
            commons = await _search_commons(primary, limit=4)
            openverse = await _search_openverse(primary, limit=4)
            logger.info(
                f"illustrate image: Commons={len(commons)} Openverse={len(openverse)} "
                f"(judging up to {remaining} more)"
            )
            more = await _judge_pool(
                commons + openverse, subject, content, model_id, seen_urls, budget=remaining
            )
            all_judged.extend(more)

        winner = _pick_winner(all_judged)
        if winner is None:
            logger.info(
                f"illustrate image: no candidate cleared τ={GATE_CONFIDENCE_THRESHOLD} "
                f"for {message_id} → ABSTAIN (none)"
            )
            await _write_sidecar(message_id, session_id, mode="none")
            return "none"
        return await _finish_image(winner, subject, message_id, session_id, model_id)
    except Exception as e:
        logger.warning(f"illustrate image pipeline failed for {message_id} → none: {e}")
        await _write_sidecar(message_id, session_id, mode="none")
        return "none"


async def illustrate(
    session_id: str,
    message_id: str,
    notebook_id: Optional[str] = None,
    model_id: Optional[str] = None,
) -> str:
    """Enrich one AI chat message. Returns the final mode
    ('diagram' | 'image' | 'none').

    Never raises: any failure resolves to ``'none'``. The image path runs its
    candidate→judge pipeline (W2) but only ever writes ``mode='image'`` once the
    W3 seam (``_fetch_and_store_image``) returns a stored MediaItem; until W3
    lands, a gated image resolves to ``'none'`` (deliberate abstain).
    """
    try:
        full_session_id = _prefixed(session_id, "chat_session")
        resolved_model = await _resolve_illustration_model_id(model_id)

        content = await _load_message_content(full_session_id, message_id)
        if not content or not content.strip():
            logger.info(f"illustrate: message {message_id} not found / empty → none")
            return "none"

        # Stage 1 — cheap heuristic.
        if _cheap_prefilter_skip(content):
            logger.debug(f"illustrate: prefilter skipped {message_id} → none")
            await _write_sidecar(message_id, session_id, mode="none")
            return "none"

        # Stage 2 — constrained qwen3.6 JSON decision.
        decision = await _run_gate(content, resolved_model)
        illustrate_flag = bool(decision.get("illustrate"))
        mode = str(decision.get("mode") or "none")
        try:
            confidence = float(decision.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        subject = str(decision.get("subject") or "").strip()

        gate_on = (
            illustrate_flag
            and confidence >= GATE_CONFIDENCE_THRESHOLD
            and mode in ("diagram", "image")
        )
        logger.info(
            f"illustrate gate for {message_id}: illustrate={illustrate_flag} "
            f"mode={mode} confidence={confidence:.2f} subject={subject!r} → "
            f"{'ON' if gate_on else 'none'}"
        )
        if not gate_on:
            await _write_sidecar(message_id, session_id, mode="none")
            return "none"

        # ---- IMAGE PATH (W2 candidate→judge; W3 fills the fetch/store seam) --
        # The gate chose an image. Expand → search (PageImages-first, early-exit)
        # → VLM relevance/abstain, then hand the chosen URL to the W3 seam. The
        # seam is a stub in W2 → this still resolves to 'none' (deliberate).
        if mode == "image":
            return await _run_image_pipeline(
                subject=subject,
                content=content,
                message_id=message_id,
                session_id=session_id,
                model_id=resolved_model,
            )
        # ---------------------------------------------------------------------

        # Diagram path.
        diagram = await _generate_diagram(content, subject, resolved_model)
        if not diagram:
            logger.info(f"illustrate: no valid mermaid for {message_id} → none")
            await _write_sidecar(message_id, session_id, mode="none")
            return "none"

        await _write_sidecar(message_id, session_id, mode="diagram", diagram=diagram)
        logger.info(f"illustrate: wrote diagram sidecar for {message_id}")
        return "diagram"
    except Exception as e:  # pragma: no cover - top-level safety net
        logger.warning(f"illustrate: unexpected failure for {message_id} → none: {e}")
        return "none"
