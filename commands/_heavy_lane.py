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

The lane must be **loop-agnostic**: surreal-commands runs every command on its
own thread with a fresh event loop (``core/executor.py`` — ``threading.Thread``
+ ``asyncio.new_event_loop``). An ``asyncio.Lock`` shared across those commands
binds to whichever loop first *contends* for it, and then wakes its waiters by
setting a future on that loop — which, for every other command, is a loop that
is not running. Uncontended acquires never touch the loop, so the bug stays
invisible until two heavy jobs overlap, at which point they deadlock in silence.
``threading.Lock`` has no loop affinity, so the lane is built on that and awaited
off-loop, keeping the waiting command's loop responsive.
"""

import asyncio
import threading
from contextlib import nullcontext
from typing import AsyncContextManager, Optional

from loguru import logger

from open_notebook.ai.claude_agent import (
    CLAUDE_AGENT_OVERRIDE_PREFIX,
    is_claude_agent_selected,
)
from open_notebook.ai.models import DefaultModels, Model

# Providers whose models run on the local heavy slot (stored with underscores in
# the DB; ds4 is registered as an ``openai_compatible`` endpoint).
HEAVY_PROVIDERS = {"ollama", "openai_compatible"}

class _HeavyLane:
    """Process-wide async mutex that is safe across threads and event loops.

    Drop-in for ``async with`` on an ``asyncio.Lock``. Waiting happens in a
    worker thread so the caller's loop keeps servicing its own tasks (progress
    writes, heartbeats) while it queues for the slot.
    """

    __slots__ = ("_lock",)

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def locked(self) -> bool:
        return self._lock.locked()

    async def __aenter__(self) -> "_HeavyLane":
        # Fast path: uncontended acquire never leaves the loop.
        if self._lock.acquire(blocking=False):
            return self

        # Contended: poll in short slices off-loop. A plain blocking acquire in
        # a thread would keep running after a cancellation and leak the lock;
        # slicing bounds that window, and `held` lets us hand it back if the
        # awaiting task is cancelled between the acquire and our return.
        held: list[bool] = []

        def _acquire_slice() -> bool:
            got = self._lock.acquire(timeout=0.5)
            if got:
                held.append(True)
            return got

        try:
            while not await asyncio.to_thread(_acquire_slice):
                pass
        except asyncio.CancelledError:
            if held:
                self._lock.release()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._lock.release()
        return False


# Process-wide lane serializing heavy local-model generations.
heavy_lane = _HeavyLane()


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


async def is_heavy_model_id(model_id: Optional[str]) -> bool:
    """Return True if ``model:<id>`` runs on the local heavy slot.

    The id-based counterpart to :func:`is_heavy_model`, for non-chat commands
    that already know which model they resolved. Resolution failures are
    treated as non-heavy so a lookup error never blocks the lane.
    """
    if not model_id:
        return False
    try:
        model = await Model.get(model_id)
        return bool(model and model.provider in HEAVY_PROVIDERS)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"is_heavy_model_id resolution failed for {model_id!r}: {e}")
        return False


async def heavy_lane_for(model_id: Optional[str]) -> AsyncContextManager:
    """Return the heavy lane for a local model, else a no-op context.

    Lets a command write one unconditional ``async with`` around its generation
    without branching. Cloud models keep using the worker's remaining slots.
    """
    if await is_heavy_model_id(model_id):
        return heavy_lane
    return nullcontext()
