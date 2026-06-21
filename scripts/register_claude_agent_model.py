"""Idempotently register the Claude Agent language model and make it the default.

The "Claude Agent" model talks to Claude through your already-logged-in Claude Code
CLI (Pro/Max subscription) rather than the Anthropic API, so it needs no API key.

Run from the repo root once the dev SurrealDB is up:

    uv run python scripts/register_claude_agent_model.py

It loads the local ``.env`` automatically (so ``SURREAL_*`` connection settings are
picked up), creates a single ``provider="claude_agent" type="language"`` Model record
if one does not already exist, and points the default chat / tools / large-context
models at it. Safe to run repeatedly — it never creates a duplicate record.
"""

import asyncio

from loguru import logger

from open_notebook.ai.claude_agent import CLAUDE_AGENT_PROVIDER
from open_notebook.ai.models import DefaultModels, Model
from open_notebook.database.repository import repo_query

MODEL_NAME = "claude-agent"


def _load_env() -> None:
    """Load .env so SURREAL_* connection settings are available (best-effort)."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # pragma: no cover - dotenv is optional
        pass


async def _get_or_create_model() -> Model:
    existing = await repo_query(
        "SELECT * FROM model WHERE provider=$provider AND type='language' LIMIT 1;",
        {"provider": CLAUDE_AGENT_PROVIDER},
    )
    if existing:
        model = Model(**existing[0])
        logger.info(f"Claude Agent model already registered: {model.id}")
        return model

    model = Model(name=MODEL_NAME, provider=CLAUDE_AGENT_PROVIDER, type="language")
    await model.save()
    logger.info(f"Created Claude Agent model: {model.id}")
    return model


async def main() -> None:
    _load_env()

    model = await _get_or_create_model()
    assert model.id, "Model was not assigned an id after save()"

    defaults = await DefaultModels.get_instance()
    defaults.default_chat_model = model.id
    defaults.default_tools_model = model.id
    defaults.large_context_model = model.id
    await defaults.update()

    print(f"\n✅ Claude Agent model registered: {model.id}")
    print(f"   default_chat_model  = {defaults.default_chat_model}")
    print(f"   default_tools_model = {defaults.default_tools_model}")
    print(f"   large_context_model = {defaults.large_context_model}")


if __name__ == "__main__":
    asyncio.run(main())
