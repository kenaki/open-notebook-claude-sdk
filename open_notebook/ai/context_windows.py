"""Per-model context-window lookup for the chat usage meter.

Maps an effective model id (as reported by the Claude Agent SDK, or a local
Ollama tag) to its context-window size in tokens. This supplies the
denominator for the frontend usage meter; ``None`` means "unknown" and the
meter simply hides.

Deliberately dependency-free and unit-testable: no SDK, DB, or provider
imports. Values are the approved Q-N-windowmap defaults.
"""

from typing import Optional

# Longest-prefix match table. The entry with the longest prefix that matches
# the (lowercased) model id wins, so more specific entries can be added later
# (e.g. "claude-opus-4-6-1m") without disturbing the family-wide defaults.
_PREFIX_WINDOWS: dict[str, int] = {
    # Every current Claude model family ships a 200k context window.
    "claude-": 200_000,
    # Local Ollama qwen3.6 (covers bare "qwen3.6", "qwen3.6:latest", ...).
    "qwen3.6": 262_144,
}

# Claude Code model aliases ("opus", "sonnet", "haiku", "sonnet[1m]"...) carry
# no "claude-" prefix; any model id containing one of these substrings is a
# Claude-family model. Checked only when no prefix entry matched.
_ALIAS_WINDOWS: dict[str, int] = {
    "opus": 200_000,
    "sonnet": 200_000,
    "haiku": 200_000,
}


def get_context_window(model: Optional[str]) -> Optional[int]:
    """Return the context-window size (tokens) for ``model``, or None if unknown.

    Longest-prefix match over ``_PREFIX_WINDOWS`` first, then the Claude alias
    substrings. Matching is case-insensitive. ``None``/empty/unknown model ids
    return ``None`` so the frontend meter hides rather than lying.
    """
    if not model:
        return None
    normalized = model.strip().lower()
    if not normalized:
        return None

    best_window: Optional[int] = None
    best_length = -1
    for prefix, window in _PREFIX_WINDOWS.items():
        if normalized.startswith(prefix) and len(prefix) > best_length:
            best_window = window
            best_length = len(prefix)
    if best_window is not None:
        return best_window

    for alias, window in _ALIAS_WINDOWS.items():
        if alias in normalized:
            return window

    return None
