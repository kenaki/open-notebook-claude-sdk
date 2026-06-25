"""Heavy-lane serialization for local-model chat jobs.

The surreal-commands worker runs up to N jobs concurrently (a shared
``asyncio.Semaphore``, default 5), across all command types. Local/heavy models
on this host — Ollama, the ds4 (DeepSeek-V4-Flash) OpenAI-compatible server, and
the Claude Agent CLI subprocess — cannot serve more than one generation at a time
without thrashing the single heavy memory slot (see the ds4↔Ollama heavy-slot
guardrails). This module exposes a single process-wide ``asyncio.Lock`` that the
``chat_completion`` command acquires **only** when the resolved chat model is
heavy, so local chats serialize against each other while embeddings (and cloud
chats) keep using the remaining worker slots.

The lock is created at import and binds to the worker's event loop on first
``await`` (Python ≥3.10 semantics). The worker is a single process with one loop,
so a module-level lock is the correct cross-job primitive here.
"""

import asyncio
from typing import Optional

from loguru import logger

from open_notebook.ai.claude_agent import (
    CLAUDE_AGENT_OVERRIDE_PREFIX,
    is_claude_agent_selected,
)
from open_notebook.ai.models import DefaultModels, Model

# Providers whose models run on the local heavy slot (stored with underscores in
# the DB; ds4 is registered as an ``openai_compatible`` endpoint).
HEAVY_PROVIDERS = {"ollama", "openai_compatible"}

# Process-wide lock serializing heavy local-model chat generations.
heavy_lane = asyncio.Lock()


async def is_heavy_model(model_override: Optional[str]) -> bool:
    """Return True if the effective chat model runs on the local heavy slot.

    Heavy = the Claude Agent CLI subprocess, or a Model whose provider is local
    (Ollama / ds4 via openai_compatible). ``model_override`` may be ``None`` (use
    the default chat model), a ``model:<id>`` reference, or the
    ``claude_agent::<model>`` per-chat marker. Resolution failures are treated as
    non-heavy so a lookup error never blocks the lane.
    """
    # Claude Agent (global selection, default, or per-chat override marker).
    if model_override and model_override.startswith(CLAUDE_AGENT_OVERRIDE_PREFIX):
        return True
    try:
        if await is_claude_agent_selected(model_override):
            return True

        model_id = model_override
        if not model_id:
            defaults = await DefaultModels.get_instance()
            model_id = defaults.default_chat_model if defaults else None
        if not model_id:
            return False

        model = await Model.get(model_id)
        return bool(model and model.provider in HEAVY_PROVIDERS)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"is_heavy_model resolution failed for {model_override!r}: {e}")
        return False
