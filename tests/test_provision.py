"""Unit tests for A6 — the opt-in `reasoning` flag on `provision_langchain_model`.

No real Esperanto/Ollama model is used: `model_manager.get_default_model` is
patched to hand back a fake Esperanto wrapper around a fake LangChain model, and
`provision.LanguageModel` (the isinstance check) is patched to the fake
wrapper's own class so the real Esperanto ABC never needs subclassing. This lets
us assert the duck-check precisely: reasoning is enabled ONLY when requested AND
the returned LangChain model actually declares a `reasoning` pydantic field
(mirroring `ChatOllama`), and every other combination is byte-identical.
"""

from unittest.mock import AsyncMock

import pytest

import open_notebook.ai.provision as provision_module


class FakeEsperantoModel:
    """Stands in for an `esperanto.LanguageModel` instance."""

    def __init__(self, langchain_model):
        self._langchain_model = langchain_model
        self.to_langchain_called = False

    def to_langchain(self):
        self.to_langchain_called = True
        return self._langchain_model


class FakeOllamaLikeModel:
    """Duck-types `ChatOllama`: a pydantic-ish model exposing a `reasoning` field."""

    model_fields = {"reasoning": object()}

    def __init__(self, reasoning=None):
        self.reasoning = reasoning
        self.model_copy_calls = 0

    def model_copy(self, update=None):
        new = FakeOllamaLikeModel(reasoning=self.reasoning)
        new.model_copy_calls = self.model_copy_calls
        if update:
            for key, value in update.items():
                setattr(new, key, value)
        return new


class FakeOtherProviderModel:
    """Duck-types a provider (e.g. OpenAI/Anthropic) with NO `reasoning` field."""

    model_fields: dict = {}

    def __init__(self):
        pass


@pytest.fixture
def patch_provisioning(monkeypatch):
    """Route provisioning to a fake model and satisfy the isinstance() gate."""

    def _patch(langchain_model):
        fake_esperanto_model = FakeEsperantoModel(langchain_model)
        monkeypatch.setattr(provision_module, "LanguageModel", FakeEsperantoModel)
        monkeypatch.setattr(
            provision_module.model_manager,
            "get_default_model",
            AsyncMock(return_value=fake_esperanto_model),
        )
        monkeypatch.setattr(
            provision_module.model_manager,
            "get_model",
            AsyncMock(return_value=fake_esperanto_model),
        )
        return fake_esperanto_model

    return _patch


@pytest.mark.asyncio
async def test_reasoning_false_default_leaves_ollama_like_model_untouched(
    patch_provisioning,
):
    langchain_model = FakeOllamaLikeModel(reasoning=None)
    patch_provisioning(langchain_model)

    result = await provision_module.provision_langchain_model(
        "hello", None, "chat"
    )

    # Default is False: no model_copy, no reasoning flip — byte-identical object.
    assert result is langchain_model
    assert result.reasoning is None


@pytest.mark.asyncio
async def test_reasoning_true_enables_field_on_ollama_like_model(patch_provisioning):
    langchain_model = FakeOllamaLikeModel(reasoning=None)
    patch_provisioning(langchain_model)

    result = await provision_module.provision_langchain_model(
        "hello", None, "chat", reasoning=True
    )

    assert result.reasoning is True
    # model_copy returns a new object (mirrors real pydantic model_copy semantics).
    assert result is not langchain_model


@pytest.mark.asyncio
async def test_reasoning_true_is_a_no_op_for_non_ollama_model(patch_provisioning):
    """A non-Ollama model (no `reasoning` field) is unaffected by the flag."""
    langchain_model = FakeOtherProviderModel()
    patch_provisioning(langchain_model)

    result = await provision_module.provision_langchain_model(
        "hello", None, "chat", reasoning=True
    )

    assert result is langchain_model
    assert not hasattr(result, "reasoning")


@pytest.mark.asyncio
async def test_reasoning_kwarg_not_forwarded_to_model_manager(patch_provisioning):
    """`reasoning` must never leak into the `**kwargs` passed to ModelManager."""
    langchain_model = FakeOllamaLikeModel()
    fake_esperanto_model = patch_provisioning(langchain_model)

    await provision_module.provision_langchain_model(
        "hello", None, "chat", reasoning=True, max_tokens=8192
    )

    _args, kwargs = provision_module.model_manager.get_default_model.call_args
    assert "reasoning" not in kwargs
    assert kwargs.get("max_tokens") == 8192
    assert fake_esperanto_model.to_langchain_called
