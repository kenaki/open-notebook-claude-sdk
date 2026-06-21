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

import os
from typing import Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
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

# None ⇒ follow the Claude Code default model (do not pin options.model).
CLAUDE_AGENT_MODEL = os.environ.get("CLAUDE_AGENT_MODEL")


def _build_options(
    system_prompt: str, mcp_servers: Optional[dict] = None
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
    # Only pin the model when explicitly configured; otherwise follow CC default.
    if CLAUDE_AGENT_MODEL:
        kwargs["model"] = CLAUDE_AGENT_MODEL
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
        turns.append(f"{role}: {content}")

    transcript = "\n\n".join(turns)
    if transcript:
        transcript += "\n\n"
    return system_prompt, transcript


async def _run(prompt: str, options: ClaudeAgentOptions) -> str:
    """Drive a single Claude Agent SDK query and return the assistant text.

    Collects ``TextBlock`` text from each ``AssistantMessage`` (skips thinking),
    and raises the appropriate ``OpenNotebookError`` subclass on a reported error.
    """
    texts: list[str] = []
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
                # Only collect plain text; ThinkingBlock and tool blocks skipped.
                if isinstance(block, TextBlock):
                    texts.append(block.text)
        elif isinstance(message, ResultMessage):
            if message.is_error:
                logger.error(
                    f"Claude Agent ResultMessage error (subtype={message.subtype}): "
                    f"{message.errors}"
                )
                _raise_for_error(None, message.errors)
            result = message.result

    if result:
        return result
    return "".join(texts)


async def generate_with_claude_agent(
    payload: list, thread_id: Optional[str] = None
) -> AIMessage:
    """Run a chat ``payload`` through the Claude Agent SDK, returning an AIMessage.

    ``thread_id`` is unused in v1 (reserved for deferred SDK session-resume); the
    transcript is re-sent statelessly each turn.

    The Open Notebook data tools (in-process MCP) are attached so Claude can read
    the user's notebooks/sources/notes during the turn.
    """
    system_prompt, transcript = _flatten(payload)
    # Lazy import keeps this module import-light: the tools pull in the domain/DB
    # layer, which we deliberately keep out of module-top imports.
    from open_notebook.ai.claude_agent_tools import (
        MCP_SERVER_NAME,
        build_open_notebook_mcp_server,
    )

    mcp_servers = {MCP_SERVER_NAME: build_open_notebook_mcp_server()}
    text = await _run(
        transcript, _build_options(system_prompt, mcp_servers=mcp_servers)
    )
    return AIMessage(content=text)


async def is_claude_agent_selected(model_id: Optional[str]) -> bool:
    """Return True if the effective chat model is the claude_agent sentinel.

    Resolves the effective model id (falling back to the configured default chat
    model when ``model_id`` is falsy) and checks the loaded ``Model`` record's
    provider. Must NOT route through ``ModelManager.get_model`` (Esperanto has no
    such provider and would error).
    """
    effective_id = model_id
    if not effective_id:
        try:
            defaults = await DefaultModels.get_instance()
            effective_id = defaults.default_chat_model
        except Exception as e:
            logger.warning(f"Could not load default chat model: {e}")
            return False

    if not effective_id:
        return False

    try:
        model = await Model.get(effective_id)
    except Exception:
        return False

    return model.provider == CLAUDE_AGENT_PROVIDER
