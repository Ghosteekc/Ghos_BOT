"""Stage 1: backend / mode / Ollama config selection (minimal)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from bot.services.ghosteek_ai.llm.base import LLMConfig
from bot.services.ghosteek_ai.llm.provider import (
    OllamaProvider,
    QwenLLMProvider,
    get_llm_provider,
    ollama_config_from_settings,
)
from bot.services.ghosteek_ai.llm.runtime_capabilities import reset_capability_warnings


@pytest.fixture(autouse=True)
def _reset_warnings():
    reset_capability_warnings()
    yield
    reset_capability_warnings()


def test_a_backend_ollama_resolves_to_ollama_provider():
    """A) GHOSTEEK_AI_BACKEND=ollama → OllamaProvider."""
    from bot.services.ghosteek_ai import service as svc

    with patch.object(svc, "_configured_backend", return_value="ollama"):
        assert svc._configured_backend() == "ollama"
        provider = svc._resolve_provider("ollama")
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"
    assert get_llm_provider("ollama").name == "ollama"


def test_b_backend_qwen_resolves_to_cloud_provider():
    """B) GHOSTEEK_AI_BACKEND=qwen → cloud Qwen provider (not Ollama)."""
    from bot.services.ghosteek_ai import service as svc

    provider = svc._resolve_provider("qwen")
    assert isinstance(provider, QwenLLMProvider)
    assert not isinstance(provider, OllamaProvider)
    # name is qwen, or groq if LLM_BASE_URL points at groq.com (shared cloud class).
    assert provider.name in {"qwen", "groq"}
    assert provider.config.provider in {"qwen", "groq"}


def test_c_backend_groq_resolves_to_cloud_groq_provider():
    """C) GHOSTEEK_AI_BACKEND=groq → cloud/Groq provider (not Ollama)."""
    from bot.services.ghosteek_ai import service as svc

    provider = svc._resolve_provider("groq")
    assert isinstance(provider, QwenLLMProvider)
    assert provider.name == "groq"
    assert not isinstance(provider, OllamaProvider)


def test_d_ollama_qwen3_8b_uses_planner_capability_profile():
    """D) ollama + qwen3:8b → planner / local renderer-first (not Agent)."""
    from bot.services.ghosteek_ai import service as svc

    provider = OllamaProvider(
        LLMConfig(
            provider="ollama",
            model="qwen3:8b",
            extra={"enable_tools": False, "think": False, "num_ctx": 2048, "num_predict": 192},
        )
    )
    caps = provider.capabilities()
    assert caps.supports_tools is False
    assert caps.supports_agent_loop is False
    assert caps.supports_renderer is True
    assert svc._force_planner_first("ollama", provider) is True
    assert svc._is_local_renderer_first("ollama", provider) is True
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="ollama") == "planner"
    with patch.object(svc, "_configured_mode", return_value="planner"):
        assert svc._resolve_runtime_mode(provider, backend="ollama") == "planner"


def test_e_ollama_enable_tools_true_still_not_agent_for_qwen3_8b():
    """E) ollama + OLLAMA_ENABLE_TOOLS=true → still NOT Agent Mode for qwen3:8b."""
    from bot.services.ghosteek_ai import service as svc

    provider = OllamaProvider(
        LLMConfig(
            provider="ollama",
            model="qwen3:8b",
            extra={"enable_tools": True},
        )
    )
    assert provider.supports_tools() is False
    assert provider.capabilities().supports_agent_loop is False
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="ollama") == "planner"
    with patch.object(svc, "_configured_mode", return_value="agent"):
        assert svc._resolve_runtime_mode(provider, backend="ollama") == "planner"


def test_ollama_settings_defaults_reach_payload():
    """Settings defaults: think=false, temp=0.4, num_predict=220, num_ctx=2048."""
    cfg = ollama_config_from_settings()
    assert cfg.provider == "ollama"
    assert cfg.temperature == 0.4
    assert cfg.max_tokens == 220
    assert cfg.extra["num_predict"] == 220
    assert cfg.extra["num_ctx"] == 2048
    assert cfg.extra["think"] is False
    assert cfg.extra["enable_tools"] is False

    provider = OllamaProvider(cfg)
    from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole

    req = provider._normalize_request(
        [ChatMessage(role=MessageRole.USER, content="ping")]
    )
    body = provider._payload(req, stream=False)
    assert body["think"] is False
    assert body["options"]["temperature"] == 0.4
    assert body["options"]["num_predict"] == 220
    assert body["options"]["num_ctx"] == 2048
    assert "think" not in body["options"]


def test_default_backend_remains_cloud_safe_qwen():
    """Production-safe default in Settings is qwen (Ollama is opt-in)."""
    from bot.config import Settings

    assert Settings.model_fields["ghosteek_ai_backend"].default == "qwen"
    assert Settings.model_fields["ghosteek_ai_mode"].default == "auto"
    assert Settings.model_fields["ollama_model"].default == "qwen3:8b"
    assert Settings.model_fields["ollama_think"].default is False
    assert Settings.model_fields["ollama_num_predict"].default == 220
    assert Settings.model_fields["ollama_num_ctx"].default == 2048
    assert Settings.model_fields["ollama_enable_tools"].default is False
    assert Settings.model_fields["ollama_temperature"].default == 0.4


def test_railway_ollama_remaps_to_groq_when_llm_configured():
    """On Railway, ollama + LLM_* (Groq) → cloud groq so chat is not dead templates."""
    from bot.services.ghosteek_ai import service as svc

    with (
        patch.object(svc.settings, "ghosteek_ai_backend", "ollama"),
        patch.object(svc.settings, "llm_api_key", "gsk_test"),
        patch.object(svc.settings, "llm_base_url", "https://api.groq.com/openai/v1"),
        patch("bot.config._running_on_railway", return_value=True),
    ):
        assert svc._configured_backend() == "groq"

    with (
        patch.object(svc.settings, "ghosteek_ai_backend", "ollama"),
        patch.object(svc.settings, "llm_api_key", "gsk_test"),
        patch.object(svc.settings, "llm_base_url", "https://api.groq.com/openai/v1"),
        patch("bot.config._running_on_railway", return_value=False),
    ):
        assert svc._configured_backend() == "ollama"
