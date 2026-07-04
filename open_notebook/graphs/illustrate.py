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

W2 builds the candidate→judge HALF of the image pipeline: query expansion →
search (Wikipedia PageImages first, with early-exit; else Wikimedia Commons +
Openverse) → qwen3.6 VLM relevance judge with **abstain** (rank + threshold at τ,
top-K candidates). It hands the chosen external URL to ``_fetch_and_store_image``.

W3 (this chunk) fills ``_fetch_and_store_image``: the chosen URL is turned into a
stored, SAME-ORIGIN ``MediaItem`` via, in order, (1) an SSRF pre-check of the URL,
(2) a **fail-closed** qwen3.6-VL safety judge (unsafe / error → abstain), (3) an
SSRF-guarded, byte-capped, redirect-revalidating storage fetch that PINS the
validated IP (defeats DNS-rebinding), (4) a Pillow decode → WebP re-encode that
strips EXIF/metadata, and (5) a content-addressed atomic store under
``CHAT_MEDIA_FOLDER``. Returning the ``MediaItem`` dict makes ``_finish_image``
write the ``mode='image'`` sidecar; any failure anywhere → ``None`` → ``mode='none'``.
"""

import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
import tempfile
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from ai_prompter import Prompter
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from open_notebook.ai.models import DefaultModels
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.config import CHAT_MEDIA_FOLDER
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

# ---- Image safety + SSRF-guarded storage fetch (W3) -----------------------
# The safety judge (D3, fail-closed) reuses ``_invoke_vlm``; qwen3.6 is a
# thinking model, so leave room for the <think> block before the tiny JSON.
_SAFETY_MAX_TOKENS = 3072

# STORAGE fetch (distinct from the judge-only fetch above): the bytes we persist
# and later serve from ``/api/chat/media/{file}``. Because the URL originates
# from an external search API, it is treated as attacker-influenceable and gets
# the full SSRF posture: DNS resolved + every address range-checked, the
# validated IP pinned for the actual TCP connection (defeats DNS rebinding),
# redirects followed MANUALLY with a full re-validation per hop (defeats
# rebind-via-redirect), and a HARD byte cap enforced on bytes actually received
# (Content-Length is never trusted).
_STORE_FETCH_TIMEOUT = 25.0
_STORE_FETCH_MAX_BYTES = 15_000_000  # 15 MB hard cap on received bytes.
_MAX_REDIRECTS = 3
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)

# WebP re-encode quality (lossy). Re-encoding strips ALL source metadata (EXIF,
# GPS, ICC, XMP) as a side effect — a deliberate privacy/safety property.
_WEBP_QUALITY = 85


class _SSRFError(Exception):
    """A candidate URL failed SSRF validation (bad scheme / DNS / IP range).

    Carries a human-readable reason for the abstain log. Kept local so nothing
    external ever has to catch it — every caller degrades to ``None``.
    """


def _ip_is_blocked(ip_str: str) -> bool:
    """True if ``ip_str`` falls in a non-public range we must never fetch from.

    Fail-closed: an unparseable address, or ANY of private / loopback /
    link-local / reserved / multicast / unspecified, is blocked — checked for
    both the address itself AND, for IPv4-mapped IPv6 (``::ffff:a.b.c.d``), the
    embedded IPv4 (which would otherwise slip past the v6 flag checks).
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # not a valid IP → refuse.
    candidates = [ip]
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        candidates.append(mapped)
    for c in candidates:
        if (
            c.is_private
            or c.is_loopback
            or c.is_link_local
            or c.is_reserved
            or c.is_multicast
            or c.is_unspecified
        ):
            return True
    return False


def _validate_public_url(url: str) -> tuple:
    """Validate one URL for the storage fetch and return the connection pin.

    Blocking (DNS): call via ``asyncio.to_thread``. Enforces the scheme
    allowlist, resolves the host itself, and range-checks EVERY resolved address
    (v4 AND v6) — if ANY resolved address is non-public the whole URL is rejected
    (a resolver returning ``[public, 127.0.0.1]`` must not sneak through).

    Returns ``(scheme, hostname, port, pinned_ip, family)`` for the FIRST
    (validated) address, which the caller pins for the TCP connection. Raises
    ``_SSRFError`` with a reason on any failure.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise _SSRFError(f"scheme {scheme!r} not in http/https allowlist")
    host = parsed.hostname
    if not host:
        raise _SSRFError("no hostname in URL")
    port = parsed.port or (443 if scheme == "https" else 80)

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise _SSRFError(f"DNS resolution failed for {host!r}: {e}")
    except Exception as e:  # noqa: BLE001 - any resolver failure → refuse
        raise _SSRFError(f"DNS error for {host!r}: {type(e).__name__}")

    resolved: list[tuple[int, str]] = []
    for family, _, _, _, sockaddr in infos:
        ip = str(sockaddr[0]).split("%")[0]  # drop any IPv6 zone id.
        if _ip_is_blocked(ip):
            raise _SSRFError(
                f"{host!r} resolves to non-public address {ip!r} — blocked"
            )
        resolved.append((family, ip))
    if not resolved:
        raise _SSRFError(f"no addresses resolved for {host!r}")

    family, pinned_ip = resolved[0]
    return (scheme, host, port, pinned_ip, family)


def _build_pinned_request(validated: tuple, current_url: str) -> tuple:
    """Turn a validated tuple + the (hostname) URL into the pinned request
    parts: ``(pinned_url, host_header, extensions)``.

    The connection targets the pinned IP, but the HTTP ``Host`` header and TLS
    SNI/cert-verification host both stay the ORIGINAL hostname (httpx verifies
    the certificate against the ``sni_hostname`` extension — empirically confirmed
    against httpx 0.28.1). This is what makes IP-pinning safe over TLS.
    """
    scheme, host, port, pinned_ip, family = validated
    parsed = urlparse(current_url)
    if family == socket.AF_INET6:
        netloc = f"[{pinned_ip}]:{port}"
    else:
        netloc = f"{pinned_ip}:{port}"
    pinned_url = urlunparse(
        (scheme, netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )
    is_default_port = (scheme == "https" and port == 443) or (
        scheme == "http" and port == 80
    )
    host_disp = f"[{host}]" if ":" in host else host
    host_header = host_disp if is_default_port else f"{host_disp}:{port}"
    extensions = {"sni_hostname": host} if scheme == "https" else {}
    return pinned_url, host_header, extensions


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


async def _safety_ok(data_uri: str, model_id: Optional[str]) -> bool:
    """qwen3.6-VL zero-shot safety judge (D3, FAIL-CLOSED).

    Returns ``True`` ONLY on an explicit ``{"safe": true}`` verdict. Any other
    verdict, an unparseable response, or any raised error → ``False`` (unsafe).
    Errors are NOT swallowed here so the caller's outer guard also degrades to
    abstain; either way the image never gets fetched-for-storage or stored.
    """
    prompt = Prompter(prompt_template="illustrate/safety").render(data={})
    raw = await _invoke_vlm(model_id, prompt, data_uri, _SAFETY_MAX_TOKENS)
    verdict = _extract_json_object(raw)
    if not isinstance(verdict, dict):
        logger.info("illustrate safety: no parseable verdict → UNSAFE (fail-closed)")
        return False
    safe = verdict.get("safe") is True
    if not safe:
        logger.info(
            f"illustrate safety: UNSAFE verdict → reject "
            f"({str(verdict.get('reason') or '')[:60]!r})"
        )
    return safe


async def _ssrf_guarded_fetch(url: str) -> Optional[bytes]:
    """Fetch ``url`` for STORAGE with the full SSRF posture. Never raises.

    Per hop (max ``_MAX_REDIRECTS``): re-validate scheme + DNS + IP ranges, pin
    the validated IP for the TCP connection (Host header + TLS SNI stay the
    hostname), and DON'T auto-follow redirects — resolve ``Location`` against the
    current URL and re-run the FULL validation on the next hop (defeats
    DNS-rebinding, incl. rebind-via-redirect). Streams the body with a HARD byte
    cap enforced on bytes actually received (``Content-Length`` is never trusted).
    Returns the raw bytes, or ``None`` on any rejection / error.
    """
    current = url
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=_STORE_FETCH_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            for hop in range(_MAX_REDIRECTS + 1):
                validated = await asyncio.to_thread(_validate_public_url, current)
                pinned_url, host_header, extensions = _build_pinned_request(
                    validated, current
                )
                async with client.stream(
                    "GET",
                    pinned_url,
                    headers={"Host": host_header, "User-Agent": _USER_AGENT},
                    extensions=extensions,
                ) as resp:
                    if resp.status_code in _REDIRECT_STATUSES:
                        location = resp.headers.get("location")
                        if not location:
                            logger.info(
                                "illustrate store-fetch: redirect without Location → reject"
                            )
                            return None
                        if hop >= _MAX_REDIRECTS:
                            logger.info(
                                f"illustrate store-fetch: exceeded {_MAX_REDIRECTS} "
                                f"redirects → reject"
                            )
                            return None
                        current = urljoin(current, location)
                        logger.info(
                            f"illustrate store-fetch: redirect hop {hop + 1} → "
                            f"re-validating {current[:80]!r}"
                        )
                        continue
                    resp.raise_for_status()
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > _STORE_FETCH_MAX_BYTES:
                            logger.info(
                                f"illustrate store-fetch: exceeded "
                                f"{_STORE_FETCH_MAX_BYTES}-byte cap → reject"
                            )
                            return None
                    return bytes(buf)
        return None
    except _SSRFError as e:
        logger.info(f"illustrate store-fetch: SSRF reject → {e}")
        return None
    except Exception as e:  # noqa: BLE001 - any transport error → abstain
        logger.info(
            f"illustrate store-fetch failed for {url[:60]!r}: {type(e).__name__}: {e}"
        )
        return None


def _decode_reencode_webp(data: bytes) -> Optional[bytes]:
    """Decode ``data`` as a real raster image via Pillow, then re-encode to WebP.

    Runs in a worker thread (Pillow is blocking). Keeps Pillow's DEFAULT
    decompression-bomb limit (does not raise it) and promotes the bomb WARNING to
    an error so an oversized-pixel image fails closed. The WebP re-encode strips
    all source metadata (EXIF/GPS/ICC/XMP). Returns WebP bytes, or ``None`` if the
    bytes are not a decodable raster image.
    """
    import warnings
    from io import BytesIO

    from PIL import Image

    try:
        with warnings.catch_warnings():
            # Fail closed on a decompression-bomb WARNING (default limit kept).
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as im:
                im.load()  # force full decode (raises on truncated/bomb payloads).
                if im.mode in ("RGBA", "LA") or (
                    im.mode == "P" and "transparency" in im.info
                ):
                    im = im.convert("RGBA")
                else:
                    im = im.convert("RGB")
                out = BytesIO()
                im.save(out, format="WEBP", quality=_WEBP_QUALITY, method=6)
                return out.getvalue()
    except Exception as e:  # noqa: BLE001 - not a usable raster image.
        logger.info(f"illustrate normalize: not a decodable image ({type(e).__name__})")
        return None


def _resolve_media_path(filename: str) -> str:
    """Resolve ``filename`` under ``CHAT_MEDIA_FOLDER`` with a path-traversal
    guard (mirrors ``api.upload_utils.resolve_within`` to avoid an
    ``open_notebook`` → ``api`` import). Raises ``ValueError`` on escape."""
    safe_name = os.path.basename(filename)
    if not safe_name:
        raise ValueError("Invalid filename")
    safe_root = os.path.realpath(CHAT_MEDIA_FOLDER)
    resolved = os.path.realpath(os.path.join(safe_root, safe_name))
    if resolved != safe_root and not resolved.startswith(safe_root + os.sep):
        raise ValueError("Invalid filename: path traversal detected")
    return resolved


def _store_webp(webp: bytes) -> Optional[str]:
    """Content-address ``webp`` as ``<sha256>.webp`` and write it atomically under
    ``CHAT_MEDIA_FOLDER``. The hash filename gives natural dedupe (identical bytes
    → same name → skip the rewrite). Returns the filename, or ``None`` on failure.
    Blocking (disk I/O): call via ``asyncio.to_thread``.
    """
    try:
        digest = hashlib.sha256(webp).hexdigest()
        filename = f"{digest}.webp"
        dest = _resolve_media_path(filename)  # defense-in-depth containment check.
        if os.path.exists(dest):
            return filename  # dedupe: already stored.
        os.makedirs(CHAT_MEDIA_FOLDER, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=CHAT_MEDIA_FOLDER, suffix=".webp.tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(webp)
            os.replace(tmp, dest)  # atomic within the same directory.
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return filename
    except Exception as e:  # noqa: BLE001 - storage failure → abstain.
        logger.warning(f"illustrate store: failed to write WebP: {type(e).__name__}: {e}")
        return None


async def _fetch_and_store_image(
    candidate: dict,
    subject: str,
    message_id: str,
    session_id: str,
    model_id: Optional[str],
) -> Optional[dict]:
    """W3 — turn the chosen candidate into a stored, safe ``MediaItem`` dict.

    Order (fail-closed at every step; NOTHING raises out of this function):
    1. **SSRF pre-check** of ``candidate['url']`` (scheme + DNS + IP ranges).
       Rejecting here means neither the safety-judge fetch nor the storage fetch
       ever touches a non-public host — an attacker-influenced candidate URL
       (e.g. from a poisoned search response) cannot SSRF via the judge fetch.
    2. **Safety judge FIRST** (D3): fetch a capped throwaway copy of the bytes
       (reusing the W2 judge-fetch) and send them to qwen3.6-VL. Unsafe verdict /
       parse failure / any error → abstain. The STORAGE fetch below never runs
       until the verdict is safe.
    3. **SSRF-guarded storage fetch** (re-validates + pins + manual redirect
       re-validation + hard byte cap).
    4. **Normalize**: Pillow decode (default bomb limit) → re-encode to WebP
       (strips EXIF) in a worker thread.
    5. **Store**: ``sha256(webp)`` filename, atomic write under
       ``CHAT_MEDIA_FOLDER`` (traversal-guarded), natural dedupe.
    6. Return ``{"type": "image", "url": "/api/chat/media/<hash>.webp",
       "label": candidate.get("title") or subject}`` — the truthy return makes the
       caller (``_finish_image``) write the ``mode='image'`` sidecar.

    Any failure anywhere → log + ``return None`` (→ ``mode='none'`` abstain).
    """
    url = (candidate or {}).get("url")
    if not url or not isinstance(url, str):
        logger.info(f"illustrate: chosen candidate for {message_id} has no url → none")
        return None

    try:
        # 1. SSRF pre-check — refuse non-public targets BEFORE any fetch (incl.
        #    the safety-judge fetch), so the throwaway judge fetch can't SSRF.
        try:
            await asyncio.to_thread(_validate_public_url, url)
        except _SSRFError as e:
            logger.info(f"illustrate: candidate url rejected pre-fetch → {e}")
            return None

        # 2. SAFETY FIRST (fail-closed). Reuse the W2 judge-only fetch (10 MB cap)
        #    to obtain the bytes the VLM judges — NO storage fetch happens yet.
        judge_uri = await _fetch_image_data_uri(url)
        if not judge_uri:
            logger.info(f"illustrate: could not fetch bytes for safety judge → none")
            return None
        try:
            safe = await _safety_ok(judge_uri, model_id)
        except Exception as e:  # noqa: BLE001 - fail-closed on judge error.
            try:
                _, msg = classify_error(e)
            except Exception:
                msg = str(e)
            logger.info(f"illustrate safety judge errored → UNSAFE (fail-closed): {msg}")
            return None
        if not safe:
            return None

        # 3. Storage fetch — SSRF-guarded, byte-capped, redirect-revalidating.
        raw = await _ssrf_guarded_fetch(url)
        if not raw:
            return None

        # 4. Normalize to WebP (strips metadata) off the event loop.
        webp = await asyncio.to_thread(_decode_reencode_webp, raw)
        if not webp:
            return None

        # 5. Content-addressed atomic store + natural dedupe.
        filename = await asyncio.to_thread(_store_webp, webp)
        if not filename:
            return None

        media = {
            "type": "image",
            "url": f"/api/chat/media/{filename}",
            "label": (candidate.get("title") or subject or "").strip() or "Illustration",
        }
        logger.info(
            f"illustrate: stored safe image for {message_id} → "
            f"{media['url']} (source={candidate.get('source')!r} "
            f"conf={candidate.get('confidence')})"
        )
        return media
    except Exception as e:  # noqa: BLE001 - top-level safety net; never raise.
        logger.warning(
            f"illustrate: fetch/store failed for {message_id} → none: "
            f"{type(e).__name__}: {e}"
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
