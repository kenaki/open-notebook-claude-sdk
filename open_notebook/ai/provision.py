from esperanto import LanguageModel
from langchain_core.language_models.chat_models import BaseChatModel
from loguru import logger

from open_notebook.ai.models import model_manager
from open_notebook.exceptions import ConfigurationError
from open_notebook.utils import token_count


async def provision_langchain_model(
    content, model_id, default_type, *, reasoning: bool = False, **kwargs
) -> BaseChatModel:
    """
    Returns the best model to use based on the context size and on whether there is a specific model being requested in Config.
    If context > 105_000, returns the large_context_model
    If model_id is specified in Config, returns that model
    Otherwise, returns the default model for the given type

    ``reasoning``: opt-in (default False, byte-identical behavior/latency for every
    existing caller). When True AND the provisioned LangChain model actually exposes
    a ``reasoning`` field (currently only ``langchain_ollama.ChatOllama`` — duck-checked
    via ``model_fields`` so other providers are untouched and ``ChatOllama`` is never
    imported here), returns a copy with that field enabled so the provider surfaces
    reasoning text on ``additional_kwargs["reasoning_content"]`` (see graphs/chat.py,
    graphs/source_chat.py).
    """
    tokens = token_count(content)
    model = None
    selection_reason = ""

    if tokens > 105_000:
        selection_reason = f"large_context (content has {tokens} tokens)"
        logger.debug(
            f"Using large context model because the content has {tokens} tokens"
        )
        model = await model_manager.get_default_model("large_context", **kwargs)
    elif model_id:
        selection_reason = f"explicit model_id={model_id}"
        model = await model_manager.get_model(model_id, **kwargs)
    else:
        selection_reason = f"default for type={default_type}"
        model = await model_manager.get_default_model(default_type, **kwargs)

    logger.debug(f"Using model: {model}")

    if model is None:
        logger.error(
            f"Model provisioning failed: No model found. "
            f"Selection reason: {selection_reason}. "
            f"model_id={model_id}, default_type={default_type}. "
            f"Please check Settings → Models and ensure a default model is configured for '{default_type}'."
        )
        raise ConfigurationError(
            f"No model configured for {selection_reason}. "
            f"Please go to Settings → Models and configure a default model for '{default_type}'."
        )

    if not isinstance(model, LanguageModel):
        logger.error(
            f"Model type mismatch: Expected LanguageModel but got {type(model).__name__}. "
            f"Selection reason: {selection_reason}. "
            f"model_id={model_id}, default_type={default_type}."
        )
        raise ConfigurationError(
            f"Model is not a LanguageModel: {model}. "
            f"Please check that the model configured for '{default_type}' is a language model, not an embedding or speech model."
        )

    langchain_model = model.to_langchain()

    if reasoning:
        model_fields = getattr(type(langchain_model), "model_fields", {})
        if "reasoning" in model_fields:
            try:
                langchain_model = langchain_model.model_copy(
                    update={"reasoning": True}
                )
            except Exception as e:
                logger.warning(
                    f"Could not enable reasoning on {type(langchain_model).__name__}: {e}"
                )

    return langchain_model
