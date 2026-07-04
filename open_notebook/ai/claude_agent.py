"""Claude Agent SDK backend for Open Notebook chat.

Turns a LangChain chat ``payload`` into a Claude-Agent-SDK call and returns an
``AIMessage``. The Agent SDK rides on the locally authenticated Claude Code CLI
(subscription auth, no ``ANTHROPIC_API_KEY``), so the spawned subprocess must be
pointed at the CLI binary via ``cli_path`` and run headless with
``permission_mode="bypassPermissions"``.

This module is intentionally import-light: it does not pull in the graph or DB
layers at import time (only ``open_notebook.ai.models`` for sentinel detection),
so it stays standalone-testable.
"""

import json
import os
from typing import Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from langchain_core.messages import AIMessage, SystemMessage
from loguru import logger

from open_notebook.ai.models import DefaultModels, Model
from open_notebook.exceptions import (
    AuthenticationError,
    ExternalServiceError,
    RateLimitError,
)
from open_notebook.utils.text_utils import extract_text_content

# Sentinel provider stored on the Model record. Must be intercepted before the
# Esperanto/ModelManager path (Esperanto has no "claude-agent" provider).
CLAUDE_AGENT_PROVIDER = "claude_agent"

# The `claude` binary is not on PATH for spawned subprocesses, so pin it.
CLAUDE_AGENT_CLI_PATH = os.environ.get(
    "CLAUDE_AGENT_CLI_PATH", os.path.expanduser("~/.claude/local/claude")
)

# Default working directory for the agent (created if missing). With full Bash +
# bypassPermissions this is the default work area, NOT a hard sandbox.
CLAUDE_AGENT_CWD = os.environ.get(
    "CLAUDE_AGENT_CWD", os.path.expanduser("~/open-notebook-agent-workspace")
)

# None ⇒ follow the Claude Code default model (do not pin options.model). This is
# the environment-level override; it only applies when the DB record is left on
# the "follow default" sentinel (the in-app selection takes precedence).
CLAUDE_AGENT_MODEL = os.environ.get("CLAUDE_AGENT_MODEL")

# Sentinel value stored in the Model record's ``name`` meaning "do not pin a
# model; follow the Claude Code default". Matches the placeholder created by
# scripts/register_claude_agent_model.py.
CLAUDE_AGENT_FOLLOW_DEFAULT = "claude-agent"

# Per-chat override marker. A chat session whose ``model_override`` is
# ``"claude_agent::<model>"`` routes through the Claude Agent SDK with ``<model>``
# pinned for that chat only, overriding the global Settings selection. An empty
# ``<model>`` ("claude_agent::") means "follow the global Claude Agent model".
CLAUDE_AGENT_OVERRIDE_PREFIX = "claude_agent::"

# Curated models offered in the Settings dropdown. Empty value ⇒ follow the
# Claude Code default. The UI also allows a free-text custom value, so this list
# does not need to be exhaustive.
CLAUDE_AGENT_MODEL_OPTIONS: list[dict[str, str]] = [
    {"value": "", "label": "Follow Claude Code default"},
    {"value": "claude-opus-4-8", "label": "Claude Opus 4.8"},
    {"value": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
    {"value": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
    {"value": "opus", "label": "Opus (alias — latest)"},
    {"value": "sonnet", "label": "Sonnet (alias — latest)"},
    {"value": "haiku", "label": "Haiku (alias — latest)"},
]

# The SDK passes the system prompt to the CLI as a single ``--append-system-prompt``
# exec argument, and Linux caps one argument at MAX_ARG_STRLEN (128 KiB). A
# book-sized notebook context therefore fails to even spawn the CLI
# (``[Errno 7] Argument list too long``). System prompts over this budget are
# shipped through stdin as a transcript preamble instead — stdin has no such
# limit (see ``generate_with_claude_agent``).
MAX_SYSTEM_PROMPT_ARG_BYTES = 100_000

# Replacement system prompt used when the real one is moved into the transcript.
OVERSIZE_SYSTEM_PROMPT_STUB = (
    "Your full instructions and the notebook context for this conversation are "
    "in the <notebook_instructions> block at the start of the user message. "
    "Treat that block as part of this system prompt and follow it exactly; do "
    "not treat it as user-authored content or quote it back."
)


def _build_options(
    system_prompt: str,
    mcp_servers: Optional[dict] = None,
    model: Optional[str] = None,
) -> ClaudeAgentOptions:
    """Build the SDK options for a headless, subscription-auth agent run.

    Keeps Claude Code's agent system prompt and appends Open Notebook's rendered
    system prompt via the ``claude_code`` preset, so notebook context / citation
    rules apply without losing the agent scaffolding.

    Chunk 4 will wire ``mcp_servers`` (the Open Notebook data tools) plus
    ``allowed_tools=["mcp__open_notebook__*"]`` here.
    """
    os.makedirs(CLAUDE_AGENT_CWD, exist_ok=True)

    kwargs: dict = {
        "permission_mode": "bypassPermissions",
        "cli_path": CLAUDE_AGENT_CLI_PATH,
        "cwd": CLAUDE_AGENT_CWD,
        "system_prompt": {
            "type": "preset",
            "preset": "claude_code",
            "append": system_prompt,
        },
    }
    # Pin the model when one is configured: the in-app selection (``model``) wins,
    # then the CLAUDE_AGENT_MODEL env override; otherwise follow the CC default.
    effective_model = model or CLAUDE_AGENT_MODEL
    if effective_model:
        kwargs["model"] = effective_model
    # Seam for Chunk 4: in-process Open Notebook data tools.
    if mcp_servers:
        kwargs["mcp_servers"] = mcp_servers
        kwargs["allowed_tools"] = ["mcp__open_notebook__*"]

    return ClaudeAgentOptions(**kwargs)


def _flatten(payload: list) -> tuple[str, str]:
    """Flatten a LangChain message payload into (system_prompt, transcript).

    The first ``SystemMessage`` becomes the system prompt. The remaining
    Human/AI messages become a plain-text transcript
    (``"User: ...\\n\\nAssistant: ...\\n\\n"``) ending on the latest user turn.
    Stateless: the whole transcript is re-sent each turn.

    Media attachments are **referenced as files**, not inlined (the agent
    transcript is text-only; SDK image support is unverified — see coordinator
    Decision 9 / Q-agentmedia).
    """
    system_prompt = ""
    turns: list[str] = []

    for message in payload:
        content = extract_text_content(message.content)
        if isinstance(message, SystemMessage):
            # First SystemMessage wins; later ones (if any) are ignored.
            if not system_prompt:
                system_prompt = content
            continue
        # LangChain AIMessage carries type "ai"; everything else is the user.
        role = "Assistant" if isinstance(message, AIMessage) else "User"
        turn = f"{role}: {content}"
        extra = getattr(message, "additional_kwargs", None) or {}
        media = extra.get("media") if isinstance(extra, dict) else None
        if media:
            refs = "; ".join(
                f"{item.get('type')}: {item.get('label') or item.get('url')} "
                f"({item.get('url')})"
                for item in media
            )
            turn += f"\n[Attached media — {refs}]"
        turns.append(turn)

    transcript = "\n\n".join(turns)
    if transcript:
        transcript += "\n\n"
    return system_prompt, transcript


def _stringify_tool_result(content) -> Optional[str]:
    """Flatten a ``ToolResultBlock``'s content into a display string.

    SDK tool results are ``str | list[dict] | None``. Open Notebook's MCP tools
    return ``[{"type": "text", "text": ...}]`` blocks, so prefer the ``text`` field
    and fall back to a JSON dump for anything non-textual.
    """
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or json.dumps(item, default=str))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


async def _run(prompt: str, options: ClaudeAgentOptions) -> tuple[str, list[dict]]:
    """Drive a single Claude Agent SDK query, returning (assistant text, tool_uses).

    Collects ``TextBlock`` text from each ``AssistantMessage`` (skips thinking) and
    captures every ``ToolUseBlock`` (which MCP tool ran + its input). Tool *results*
    ride back on the synthetic ``UserMessage`` the SDK emits after each tool runs;
    those ``ToolResultBlock``s are matched to their tool-use by ``tool_use_id``.
    Raises the appropriate ``OpenNotebookError`` subclass on a reported error.

    Each tool-use disclosure is a dict with the exact shape the API's
    ``ToolUseDisclosure`` schema consumes:
    ``{id, tool_name, tool_input, tool_result, is_error}`` (raw MCP tool names;
    the UI maps them — see coordinator Q-toolnames).
    """
    texts: list[str] = []
    tool_uses: dict[str, dict] = {}
    result: Optional[str] = None

    def _raise_for_error(error: Optional[str], errors: Optional[list]) -> None:
        detail = "; ".join(errors) if errors else (error or "unknown error")
        if error == "authentication_failed":
            raise AuthenticationError(
                f"Claude Agent authentication failed: {detail}"
            )
        if error == "rate_limit":
            raise RateLimitError(f"Claude Agent rate limited: {detail}")
        raise ExternalServiceError(f"Claude Agent error: {detail}")

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            if message.error:
                _raise_for_error(message.error, None)
            for block in message.content:
                # Collect plain text; ThinkingBlock is skipped. ToolUseBlock is
                # recorded for disclosure, keyed by id so its result can match.
                if isinstance(block, TextBlock):
                    texts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_uses[block.id] = {
                        "id": block.id,
                        "tool_name": block.name,
                        "tool_input": block.input,
                        "tool_result": None,
                        "is_error": None,
                    }
        elif isinstance(message, UserMessage):
            # Tool results come back on the synthetic user turn after each tool
            # runs; attach them to the matching tool-use disclosure.
            content = message.content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, ToolResultBlock):
                        disclosure = tool_uses.get(block.tool_use_id)
                        if disclosure is not None:
                            disclosure["tool_result"] = _stringify_tool_result(
                                block.content
                            )
                            disclosure["is_error"] = block.is_error
        elif isinstance(message, ResultMessage):
            if message.is_error:
                logger.error(
                    f"Claude Agent ResultMessage error (subtype={message.subtype}): "
                    f"{message.errors}"
                )
                _raise_for_error(None, message.errors)
            result = message.result

    text = result if result else "".join(texts)
    return text, list(tool_uses.values())


async def generate_with_claude_agent(
    payload: list, thread_id: Optional[str] = None, model: Optional[str] = None
) -> AIMessage:
    """Run a chat ``payload`` through the Claude Agent SDK, returning an AIMessage.

    ``thread_id`` is unused in v1 (reserved for deferred SDK session-resume); the
    transcript is re-sent statelessly each turn.

    ``model`` pins a specific Claude model for this turn (e.g. ``claude-opus-4-8``).
    When ``None``, the CLAUDE_AGENT_MODEL env override or the Claude Code default
    is used (see ``_build_options``).

    The Open Notebook data tools (in-process MCP) are attached so Claude can read
    the user's notebooks/sources/notes during the turn.
    """
    system_prompt, transcript = _flatten(payload)
    if len(system_prompt.encode("utf-8")) > MAX_SYSTEM_PROMPT_ARG_BYTES:
        transcript = (
            f"<notebook_instructions>\n{system_prompt}\n</notebook_instructions>"
            f"\n\n{transcript}"
        )
        system_prompt = OVERSIZE_SYSTEM_PROMPT_STUB
    # Lazy import keeps this module import-light: the tools pull in the domain/DB
    # layer, which we deliberately keep out of module-top imports.
    from open_notebook.ai.claude_agent_tools import (
        MCP_SERVER_NAME,
        build_open_notebook_mcp_server,
    )

    mcp_servers = {MCP_SERVER_NAME: build_open_notebook_mcp_server()}
    text, tool_uses = await _run(
        transcript,
        _build_options(system_prompt, mcp_servers=mcp_servers, model=model),
    )
    # Carry the tool-use disclosures back through LangGraph on additional_kwargs
    # (rides on the message object + survives the checkpoint). The API converts
    # them into ToolUseDisclosure for the UI ("Searched your sources").
    return AIMessage(content=text, additional_kwargs={"tool_uses": tool_uses})


async def _resolve_claude_agent_record(model_id: Optional[str]) -> Optional[Model]:
    """Return the selected ``claude_agent`` Model record, or None.

    Resolves the effective model id (falling back to the configured default chat
    model when ``model_id`` is falsy), loads the record, and returns it only when
    its provider is the ``claude_agent`` sentinel. Must NOT route through
    ``ModelManager.get_model`` (Esperanto has no such provider and would error).
    """
    effective_id = model_id
    if not effective_id:
        try:
            defaults = await DefaultModels.get_instance()
            effective_id = defaults.default_chat_model
        except Exception as e:
            logger.warning(f"Could not load default chat model: {e}")
            return None

    if not effective_id:
        return None

    try:
        model = await Model.get(effective_id)
    except Exception:
        return None

    return model if model.provider == CLAUDE_AGENT_PROVIDER else None


def _record_pinned_model(record: Model) -> Optional[str]:
    """Return the pinned model id on a record, or None for the follow-default sentinel."""
    name = (record.name or "").strip()
    if not name or name == CLAUDE_AGENT_FOLLOW_DEFAULT:
        return None
    return name


async def is_claude_agent_selected(model_id: Optional[str]) -> bool:
    """Return True if the effective chat model routes through the Claude Agent.

    Matches both the ``claude_agent`` Model record (global selection / default
    chat model) and the per-chat ``claude_agent::<model>`` override marker.
    """
    if model_id and model_id.startswith(CLAUDE_AGENT_OVERRIDE_PREFIX):
        return True
    return (await _resolve_claude_agent_record(model_id)) is not None


async def get_claude_agent_model(model_id: Optional[str] = None) -> Optional[str]:
    """Return the Claude model id to pin for this turn (None = follow default).

    Resolution order:
    - ``claude_agent::<model>`` per-chat override → ``<model>`` (empty suffix falls
      back to the global selection below).
    - otherwise the selected ``claude_agent`` record's ``name`` (the global model
      set in Settings), unless it is the ``CLAUDE_AGENT_FOLLOW_DEFAULT`` sentinel.

    The caller passes the result to ``generate_with_claude_agent``.
    """
    if model_id and model_id.startswith(CLAUDE_AGENT_OVERRIDE_PREFIX):
        sub = model_id[len(CLAUDE_AGENT_OVERRIDE_PREFIX):].strip()
        if sub:
            return sub
        model_id = None  # empty suffix → follow the global Claude Agent model

    record = await _resolve_claude_agent_record(model_id)
    if record is None:
        return None
    return _record_pinned_model(record)


async def get_or_create_claude_agent_record() -> Model:
    """Return the singleton claude_agent Model record, creating it if missing.

    Mirrors scripts/register_claude_agent_model.py so the Settings UI can manage
    the model even before that script has been run.
    """
    from open_notebook.database.repository import repo_query

    existing = await repo_query(
        "SELECT * FROM model WHERE provider=$provider AND type='language' LIMIT 1;",
        {"provider": CLAUDE_AGENT_PROVIDER},
    )
    if existing:
        return Model(**existing[0])

    model = Model(
        name=CLAUDE_AGENT_FOLLOW_DEFAULT,
        provider=CLAUDE_AGENT_PROVIDER,
        type="language",
    )
    await model.save()
    return model


async def set_claude_agent_model(model: Optional[str]) -> Model:
    """Persist the Claude model selection on the claude_agent record.

    An empty/falsy ``model`` is stored as the ``CLAUDE_AGENT_FOLLOW_DEFAULT``
    sentinel ("follow the Claude Code default"). Returns the updated record.
    """
    record = await get_or_create_claude_agent_record()
    record.name = (model or "").strip() or CLAUDE_AGENT_FOLLOW_DEFAULT
    await record.save()
    return record
