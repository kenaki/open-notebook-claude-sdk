"""Idempotently register the local Ollama models and repoint the non-chat defaults.

This wires up the DGX Spark "hybrid AI" setup (see DGX-SPARK-MIGRATION.md):

  * chat            -> claude-agent   (UNCHANGED — Claude Code subscription)
  * embedding       -> qwen3-embedding:8b   (fixes "No embedding model configured")
  * transformation  -> qwen3.6:35b           (fixes the summary crash)
  * large-context   -> qwen3.6:35b           (>105k-token jobs, provision.py)
  * tools           -> qwen3.6:35b

The Ollama models need no API key — Esperanto reads OLLAMA_API_BASE from the env
(set in .env). Run from the repo root once Ollama is up and both models are pulled:

    uv run python scripts/register_ollama_models.py

Safe to run repeatedly: it never creates a duplicate Model record and only repoints
the non-chat default slots, leaving default_chat_model alone.
"""

import asyncio

from loguru import logger

from open_notebook.ai.models import DefaultModels, Model
from open_notebook.database.repository import repo_query

OLLAMA_PROVIDER = "ollama"
LANGUAGE_MODEL_NAME = "qwen3.6:35b"
EMBEDDING_MODEL_NAME = "qwen3-embedding:8b"


def _load_env() -> None:
    """Load .env so SURREAL_* / OLLAMA_API_BASE settings are available (best-effort)."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # pragma: no cover - dotenv is optional
        pass


async def _get_or_create_model(name: str, model_type: str) -> Model:
    existing = await repo_query(
        "SELECT * FROM model WHERE provider=$provider AND type=$type AND name=$name LIMIT 1;",
        {"provider": OLLAMA_PROVIDER, "type": model_type, "name": name},
    )
    if existing:
        model = Model(**existing[0])
        logger.info(f"Ollama {model_type} model already registered: {model.name} ({model.id})")
        return model

    model = Model(name=name, provider=OLLAMA_PROVIDER, type=model_type)
    await model.save()
    logger.info(f"Created Ollama {model_type} model: {model.name} ({model.id})")
    return model


async def main() -> None:
    _load_env()

    language = await _get_or_create_model(LANGUAGE_MODEL_NAME, "language")
    embedding = await _get_or_create_model(EMBEDDING_MODEL_NAME, "embedding")
    assert language.id and embedding.id, "Model was not assigned an id after save()"

    defaults = await DefaultModels.get_instance()
    # Leave default_chat_model untouched (stays on claude-agent).
    defaults.default_embedding_model = embedding.id
    defaults.default_transformation_model = language.id
    defaults.large_context_model = language.id
    defaults.default_tools_model = language.id
    await defaults.update()

    print("\n✅ Ollama models registered and defaults repointed:")
    print(f"   default_chat_model           = {defaults.default_chat_model}  (unchanged)")
    print(f"   default_embedding_model      = {defaults.default_embedding_model}  ({EMBEDDING_MODEL_NAME})")
    print(f"   default_transformation_model = {defaults.default_transformation_model}  ({LANGUAGE_MODEL_NAME})")
    print(f"   large_context_model          = {defaults.large_context_model}  ({LANGUAGE_MODEL_NAME})")
    print(f"   default_tools_model          = {defaults.default_tools_model}  ({LANGUAGE_MODEL_NAME})")


if __name__ == "__main__":
    asyncio.run(main())
