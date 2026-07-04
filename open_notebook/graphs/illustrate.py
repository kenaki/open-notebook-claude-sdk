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

W2/W3 seam: the gate can return ``mode='image'``; the image pipeline (query
expand → search → VLM relevance/safety → fetch → store) is NOT built in W1. The
router below has a clearly-marked ``mode == "image"`` branch that currently
declines (writes ``mode='none'``); W2/W3 replace that branch with the real
pipeline and a ``mode='image'`` sidecar row.
"""

import asyncio
import json
import re
from typing import Optional

from ai_prompter import Prompter
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


async def _invoke_llm(model_id: Optional[str], prompt: str, max_tokens: int) -> str:
    """Provision qwen3.6 and run one blocking invoke off the event loop.

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
            message = await asyncio.to_thread(model.invoke, prompt)
    else:
        message = await asyncio.to_thread(model.invoke, prompt)

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


async def illustrate(
    session_id: str,
    message_id: str,
    notebook_id: Optional[str] = None,
    model_id: Optional[str] = None,
) -> str:
    """Enrich one AI chat message. Returns the final mode ('diagram' | 'none').

    Never raises: any failure resolves to ``'none'``. (``'image'`` is not produced
    in W1 — the gate may choose it, but the router declines until W2/W3.)
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

        # ---- ROUTER SEAM (W2/W3 fill this) --------------------------------
        # The gate chose an image. The image pipeline (query-expand → search →
        # VLM relevance/abstain → safety fail-closed → SSRF fetch → WebP → store
        # → mode='image' sidecar) is NOT built in W1. For now, decline; W2/W3
        # replace this branch with the real pipeline.
        if mode == "image":
            logger.info(
                f"illustrate: gate chose image for {message_id}; image pipeline "
                f"is W2/W3 → none for now"
            )
            await _write_sidecar(message_id, session_id, mode="none")
            return "none"
        # -------------------------------------------------------------------

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
