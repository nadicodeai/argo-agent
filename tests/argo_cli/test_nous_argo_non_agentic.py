"""Tests for the Nous-Argo-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"argo"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``argo-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "argo" tag namespace.

``is_nous_argo_non_agentic`` should only match the actual Nous Research
Argo-3 / Argo-4 chat family.
"""

from __future__ import annotations

import pytest

from argo_cli.model_switch import (
    _ARGO_MODEL_WARNING,
    _check_argo_model_warning,
    is_nous_argo_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "NousResearch/Argo-3-Llama-3.1-70B",
        "NousResearch/Argo-3-Llama-3.1-405B",
        "argo-3",
        "Argo-3",
        "argo-4",
        "argo-4-405b",
        "argo_4_70b",
        "openrouter/argo3:70b",
        "openrouter/nousresearch/argo-4-405b",
        "NousResearch/Argo3",
        "argo-3.1",
    ],
)
def test_matches_real_nous_argo_chat_models(model_name: str) -> None:
    assert is_nous_argo_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous Argo 3/4"
    )
    assert _check_argo_model_warning(model_name) == _ARGO_MODEL_WARNING


@pytest.mark.parametrize(
    "model_name",
    [
        # Kyle's local Modelfile — qwen3:14b under a custom tag
        "argo-brain:qwen3-14b-ctx16k",
        "argo-brain:qwen3-14b-ctx32k",
        "argo-honcho:qwen3-8b-ctx8k",
        # Plain unrelated models
        "qwen3:14b",
        "qwen3-coder:30b",
        "qwen2.5:14b",
        "claude-opus-4-6",
        "anthropic/claude-sonnet-4.5",
        "gpt-5",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek-chat",
        # Non-chat Argo models we don't warn about
        "argo-llm-2",
        "argo2-pro",
        "nous-argo-2-mistral",
        # Edge cases
        "",
        "argo",  # bare "argo" isn't the 3/4 family
        "argo-brain",
        "brain-argo-3-impostor",  # "3" not preceded by /: boundary
    ],
)
def test_does_not_match_unrelated_models(model_name: str) -> None:
    assert not is_nous_argo_non_agentic(model_name), (
        f"expected {model_name!r} NOT to be flagged as Nous Argo 3/4"
    )
    assert _check_argo_model_warning(model_name) == ""


def test_none_like_inputs_are_safe() -> None:
    assert is_nous_argo_non_agentic("") is False
    # Defensive: the helper shouldn't crash on None-ish falsy input either.
    assert _check_argo_model_warning("") == ""
