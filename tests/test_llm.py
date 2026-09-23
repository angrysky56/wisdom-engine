"""Tests for Ollama model selection in wisdom_engine.llm."""

from __future__ import annotations

import pytest

from wisdom_engine.llm import LLMUnavailableError, pick_ollama_model

INSTALLED = [{"name": "aura-ornith:35b"}, {"name": "qwen3:0.6b"}]


def test_configured_model_that_is_installed_is_used() -> None:
    assert pick_ollama_model("aura-ornith:35b", INSTALLED) == "aura-ornith:35b"


def test_configured_model_that_is_missing_fails_loudly_with_installed_list() -> None:
    with pytest.raises(LLMUnavailableError) as exc:
        pick_ollama_model("gemma4:12b", INSTALLED)
    assert "gemma4:12b" in str(exc.value) and "aura-ornith:35b" in str(exc.value)


def test_unconfigured_uses_first_installed_or_none() -> None:
    assert pick_ollama_model(None, INSTALLED) == "aura-ornith:35b"
    assert pick_ollama_model(None, []) is None
