"""Provider availability helpers.

Pure functions that check whether a provider is reachable via database
credentials or environment variables. Extracted from api/routers/models.py
so the router stays thin and these helpers are independently testable.
"""

import os
from typing import Dict, List

from esperanto import AIFactory
from loguru import logger

from open_notebook.domain.credential import Credential


async def check_provider_has_credential(provider: str) -> bool:
    """Return True if the provider has any credentials configured in the database."""
    try:
        credentials = await Credential.get_by_provider(provider)
        return len(credentials) > 0
    except Exception:
        pass
    return False


def check_azure_support(mode: str) -> bool:
    """Return True if Azure OpenAI is available for the given mode (LLM/EMBEDDING/STT/TTS)."""
    generic = (
        os.environ.get("AZURE_OPENAI_API_KEY") is not None
        and os.environ.get("AZURE_OPENAI_ENDPOINT") is not None
        and os.environ.get("AZURE_OPENAI_API_VERSION") is not None
    )
    specific = (
        os.environ.get(f"AZURE_OPENAI_API_KEY_{mode}") is not None
        and os.environ.get(f"AZURE_OPENAI_ENDPOINT_{mode}") is not None
        and os.environ.get(f"AZURE_OPENAI_API_VERSION_{mode}") is not None
    )
    return generic or specific


def check_openai_compatible_support(mode: str) -> bool:
    """Return True if the OpenAI-compatible provider is available for the given mode."""
    generic = os.environ.get("OPENAI_COMPATIBLE_BASE_URL") is not None
    specific = os.environ.get(f"OPENAI_COMPATIBLE_BASE_URL_{mode}") is not None
    generic_key = os.environ.get("OPENAI_COMPATIBLE_API_KEY") is not None
    specific_key = os.environ.get(f"OPENAI_COMPATIBLE_API_KEY_{mode}") is not None
    return generic or specific or generic_key or specific_key


async def get_provider_availability() -> Dict[str, object]:
    """Return provider availability dict with 'available', 'unavailable', 'supported_types' keys.

    Checks DB credentials first, then environment variables as fallback.
    """
    env_var_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
        "groq": "GROQ_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "xai": "XAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "voyage": "VOYAGE_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "deepgram": "DEEPGRAM_API_KEY",
        "ollama": "OLLAMA_API_BASE",
        "dashscope": "DASHSCOPE_API_KEY",
        "minimax": "MINIMAX_API_KEY",
    }

    provider_status: Dict[str, bool] = {}

    for provider, env_var in env_var_map.items():
        has_cred = await check_provider_has_credential(provider)
        has_env = os.environ.get(env_var) is not None
        provider_status[provider] = has_cred or has_env

    # Google also supports GEMINI_API_KEY
    if not provider_status.get("google"):
        provider_status["google"] = os.environ.get("GEMINI_API_KEY") is not None

    # Vertex: DB credential or env vars
    provider_status["vertex"] = (
        await check_provider_has_credential("vertex")
        or os.environ.get("VERTEX_PROJECT") is not None
    )

    # Azure: DB credential or mode-specific env vars
    provider_status["azure"] = (
        await check_provider_has_credential("azure")
        or check_azure_support("LLM")
        or check_azure_support("EMBEDDING")
        or check_azure_support("STT")
        or check_azure_support("TTS")
    )

    # OpenAI-compatible: DB credential or mode-specific env vars
    provider_status["openai_compatible"] = (
        await check_provider_has_credential("openai_compatible")
        or check_openai_compatible_support("LLM")
        or check_openai_compatible_support("EMBEDDING")
        or check_openai_compatible_support("STT")
        or check_openai_compatible_support("TTS")
    )

    available_providers = [k for k, v in provider_status.items() if v]
    unavailable_providers = [k for k, v in provider_status.items() if not v]

    esperanto_available = AIFactory.get_available_providers()

    mode_mapping = {
        "language": "LLM",
        "embedding": "EMBEDDING",
        "speech_to_text": "STT",
        "text_to_speech": "TTS",
    }

    supported_types: Dict[str, List[str]] = {}
    for provider in available_providers:
        supported_types[provider] = []

        if provider == "openai_compatible":
            esperanto_name = "openai-compatible"
            has_db_cred = await check_provider_has_credential("openai_compatible")
            for model_type, mode in mode_mapping.items():
                if (
                    model_type in esperanto_available
                    and esperanto_name in esperanto_available[model_type]
                ):
                    if has_db_cred or check_openai_compatible_support(mode):
                        supported_types[provider].append(model_type)
        elif provider == "azure":
            has_db_cred = await check_provider_has_credential("azure")
            for model_type, mode in mode_mapping.items():
                if (
                    model_type in esperanto_available
                    and provider in esperanto_available[model_type]
                ):
                    if has_db_cred or check_azure_support(mode):
                        supported_types[provider].append(model_type)
        else:
            for model_type, providers in esperanto_available.items():
                if provider in providers:
                    supported_types[provider].append(model_type)

    return {
        "available": available_providers,
        "unavailable": unavailable_providers,
        "supported_types": supported_types,
    }
