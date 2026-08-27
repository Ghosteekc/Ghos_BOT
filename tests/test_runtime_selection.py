"""Runtime selection: local renderer-first vs cloud Agent Mode."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from bot.services.ghosteek_ai.llm.base import LLMCapabilities, LLMConfig
from bot.services.ghosteek_ai.llm.provider import OllamaProvider, QwenLLMProvider
from bot.services.ghosteek_ai.llm.runtime_capabilities import (
    LOCAL_RENDERER_FIRST_PROFILES,
    is_local_renderer_first_model,
    reset_capability_warnings,
    resolve_cloud_capabilities,
    resolve_local_ollama_capabilities,
    warn_conflicting_ollama_tools_config,
)


@pytest.fixture(autouse=True)
def _reset_warnings():
    reset_capability_warnings()
    yield
    reset_capability_warnings()


def test_qwen3_8b_local_capabilities_renderer_first():
    caps = resolve_local_ollama_capabilities(
        "qwen3:8b",
        enable_tools_config=False,
    )
    assert caps.supports_tools is False
    assert caps.supports_agent_loop is False
    assert caps.supports_renderer is True


def test_qwen3_8b_enable_tools_still_forces_no_agent():
    """OLLAMA_ENABLE_TOOLS=true must NOT unlock Agent Mode for renderer-first profile."""
    caps = resolve_local_ollama_capabilities(
        "qwen3:8b",
        enable_tools_config=True,
    )
    assert caps.supports_tools is False
    assert caps.supports_agent_loop is False
    assert caps.supports_renderer is True

    provider = OllamaProvider(
        LLMConfig(
            provider="ollama",
            model="qwen3:8b",
            extra={"enable_tools": True},
        )
    )
    assert provider.supports_tools() is False
    assert provider.capabilities().supports_agent_loop is False


def test_enable_tools_conflict_logs_warning(caplog):
    with caplog.at_level(logging.WARNING):
        warn_conflicting_ollama_tools_config("qwen3:8b")
        warn_conflicting_ollama_tools_config("qwen3:8b")  # once only
    messages = [r.message for r in caplog.records if "config conflict" in r.message]
    assert len(messages) == 1
    assert "planner-first" in messages[0]
    assert "qwen3:8b" in messages[0]


def test_ollama_provider_warns_on_init_conflict(caplog):
    with caplog.at_level(logging.WARNING):
        OllamaProvider(
            LLMConfig(
                provider="ollama",
                model="qwen3:8b",
                extra={"enable_tools": True},
            )
        )
    assert any("config conflict" in r.message for r in caplog.records)


def test_runtime_mode_ollama_qwen3_8b_always_planner():
    from bot.services.ghosteek_ai import service as svc

    provider = OllamaProvider(
        LLMConfig(
            provider="ollama",
            model="qwen3:8b",
            extra={"enable_tools": True},
        )
    )
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="ollama") == "planner"
    with patch.object(svc, "_configured_mode", return_value="agent"):
        assert svc._resolve_runtime_mode(provider, backend="ollama") == "planner"
    assert svc._force_planner_first("ollama", provider) is True
    assert svc._is_local_renderer_first("ollama", provider) is True


def test_runtime_mode_cloud_groq_coach_planner():
    from bot.services.ghosteek_ai import service as svc

    caps = resolve_cloud_capabilities(enable_tools=True)
    assert caps.supports_agent_loop is True
    assert caps.supports_tools is True
    assert caps.supports_renderer is True

    provider = MagicMock()
    provider.capabilities.return_value = caps
    provider.supports_tools.return_value = True
    provider.config = LLMConfig(provider="groq", model="llama-3.3-70b", extra={"enable_tools": True})

    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="groq") == "planner"
        assert svc._force_planner_first("groq", provider) is True
    with patch.object(svc, "_configured_mode", return_value="agent"):
        assert svc._resolve_runtime_mode(provider, backend="groq") == "agent"
        assert svc._force_planner_first("groq", provider) is False


def test_qwen_cloud_provider_capabilities():
    provider = QwenLLMProvider(
        LLMConfig(
            provider="qwen",
            model="qwen-plus",
            extra={"enable_tools": True},
        )
    )
    caps = provider.capabilities()
    assert caps.supports_tools is True
    assert caps.supports_agent_loop is True
    assert caps.supports_renderer is True


def test_profile_matching_not_single_hardcoded_string():
    """Architecture uses profile tags (qwen3+8b), not only exact 'qwen3:8b'."""
    assert is_local_renderer_first_model("qwen3:8b")
    assert is_local_renderer_first_model("qwen3:8b-instruct-q4_K_M")
    assert is_local_renderer_first_model("hf.co/foo/qwen3-8b")
    assert ("qwen3", "8b") in LOCAL_RENDERER_FIRST_PROFILES
    # Larger / other families are not automatically renderer-first
    assert is_local_renderer_first_model("qwen3:32b") is False
    assert is_local_renderer_first_model("llama3.1:8b") is False


def test_local_non_profile_model_respects_enable_tools():
    """Unknown local model: enable_tools may unlock agent_loop (explicit future models)."""
    caps_off = resolve_local_ollama_capabilities("custom-local:7b", enable_tools_config=False)
    assert caps_off.supports_agent_loop is False
    caps_on = resolve_local_ollama_capabilities("custom-local:7b", enable_tools_config=True)
    assert caps_on.supports_tools is True
    assert caps_on.supports_agent_loop is True
    assert caps_on.supports_renderer is True


def test_extra_force_planner_first_override():
    caps = resolve_local_ollama_capabilities(
        "custom-local:70b",
        enable_tools_config=True,
        extra={"force_planner_first": True},
    )
    assert caps.supports_agent_loop is False
    assert caps.supports_tools is False


def test_extra_allow_agent_loop_override_for_profile():
    """Explicit allow_agent_loop can opt a profile model into Agent (advanced)."""
    caps = resolve_local_ollama_capabilities(
        "qwen3:8b",
        enable_tools_config=True,
        extra={"allow_agent_loop": True},
    )
    assert caps.supports_tools is True
    assert caps.supports_agent_loop is True
