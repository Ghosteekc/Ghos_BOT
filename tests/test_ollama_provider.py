"""Tests for Ollama provider config, payload, session lifecycle."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.ghosteek_ai.llm.base import LLMConfig, ProviderError
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.llm.provider import (
    OllamaProvider,
    _messages_for_ollama,
    get_llm_provider,
    ollama_config_from_settings,
    qwen_config_from_settings,
)


def test_messages_for_ollama_keeps_tool_role():
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="sys"),
        ChatMessage(
            role=MessageRole.TOOL,
            content='{"ok":true}',
            name="battle_analysis",
            tool_call_id="call_1",
        ),
        ChatMessage(role=MessageRole.USER, content="hi"),
    ]
    out = _messages_for_ollama(msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1]["role"] == "tool"
    assert out[1]["name"] == "battle_analysis"
    assert out[1]["tool_call_id"] == "call_1"
    assert out[2]["role"] == "user"


def test_ollama_config_reads_settings_not_hardcoded():
    cfg = ollama_config_from_settings()
    assert cfg.provider == "ollama"
    assert cfg.model  # from settings / default qwen3:8b
    assert cfg.max_tokens == cfg.extra.get("num_predict")
    assert "num_ctx" in cfg.extra
    assert "think" in cfg.extra
    assert isinstance(cfg.extra["think"], bool)
    assert isinstance(cfg.extra["enable_tools"], bool)


def test_ollama_payload_includes_think_top_level_and_num_ctx():
    cfg = LLMConfig(
        provider="ollama",
        model="qwen3:8b",
        base_url="http://127.0.0.1:11434",
        temperature=0.15,
        max_tokens=200,
        timeout_seconds=120.0,
        extra={"enable_tools": False, "num_ctx": 2048, "think": False},
    )
    provider = OllamaProvider(cfg)
    req = provider._normalize_request(
        [ChatMessage(role=MessageRole.USER, content="ping")]
    )
    body = provider._payload(req, stream=False)
    assert body["model"] == "qwen3:8b"
    assert body["think"] is False
    assert body["options"]["temperature"] == 0.15
    assert body["options"]["num_predict"] == 200
    assert body["options"]["num_ctx"] == 2048
    assert "tools" not in body
    # think must NOT be inside options (Ollama ignores it there)
    assert "think" not in body["options"]


def test_ollama_payload_omits_tools_when_disabled():
    cfg = LLMConfig(
        provider="ollama",
        model="qwen3:8b",
        temperature=0.2,
        max_tokens=128,
        extra={"enable_tools": False, "num_ctx": 4096, "think": False},
    )
    provider = OllamaProvider(cfg)
    tools = [{"type": "function", "function": {"name": "card_info"}}]
    req = provider._normalize_request(
        [ChatMessage(role=MessageRole.USER, content="карта")],
        tools=tools,
    )
    body = provider._payload(req, stream=False)
    assert "tools" not in body
    assert provider.supports_tools() is False


def test_ollama_provider_shared_session_closed():
    async def _run():
        provider = OllamaProvider(
            LLMConfig(
                provider="ollama",
                model="qwen3:8b",
                base_url="http://127.0.0.1:9",
                timeout_seconds=1.0,
                extra={"think": False, "num_ctx": 2048, "enable_tools": False},
            )
        )
        session = await provider._get_session()
        assert session is not None
        assert not session.closed
        session2 = await provider._get_session()
        assert session2 is session
        await provider.close()
        assert provider._session is None
        assert session.closed

    asyncio.run(_run())


def test_ollama_generate_connection_error_is_provider_error():
    async def _run():
        provider = OllamaProvider(
            LLMConfig(
                provider="ollama",
                model="qwen3:8b",
                base_url="http://127.0.0.1:1",
                timeout_seconds=0.5,
                max_tokens=32,
                extra={"think": False, "num_ctx": 2048, "enable_tools": False},
            )
        )
        try:
            with pytest.raises(ProviderError) as exc:
                await provider.generate(
                    [ChatMessage(role=MessageRole.USER, content="hi")]
                )
            assert exc.value.code == "OLLAMA_CONNECTION_ERROR"
        finally:
            await provider.close()

    asyncio.run(_run())


def test_get_llm_provider_ollama_vs_qwen_are_separate():
    ollama = get_llm_provider("ollama")
    qwen = get_llm_provider("qwen")
    assert isinstance(ollama, OllamaProvider)
    assert ollama.name == "ollama"
    assert qwen.name in {"qwen", "groq"}
    cloud = qwen_config_from_settings()
    assert cloud.provider in {"qwen", "groq"}
    local = ollama_config_from_settings()
    assert local.provider == "ollama"
    # Separate setting namespaces: cloud model ≠ ollama model field source.
    assert "enable_tools" in local.extra


def test_ollama_provider_supports_stream_and_tools_flag():
    enabled_flag = OllamaProvider(
        LLMConfig(provider="ollama", model="qwen3:8b", extra={"enable_tools": True})
    )
    disabled = OllamaProvider(
        LLMConfig(provider="ollama", model="qwen3:8b", extra={"enable_tools": False})
    )
    assert enabled_flag.supports_stream() is True
    # renderer-first: ENABLE_TOOLS does not unlock tools/agent
    assert enabled_flag.supports_tools() is False
    assert disabled.supports_tools() is False
    other = OllamaProvider(
        LLMConfig(provider="ollama", model="custom-local:7b", extra={"enable_tools": True})
    )
    assert other.supports_tools() is True


def test_planner_fallback_empty_plan_uses_template_without_llm():
    """Planner-first: no planned tools → template, LLM never called."""
    from bot.services.ghosteek_ai import service as svc
    from bot.services.ghosteek_ai.context.ai_context import AIContext
    from bot.services.ghosteek_ai.models import Plan

    ctx = AIContext(raw_message="привет")
    ctx.ok = True
    ctx.intent.request = "clarify"
    ctx.intent.service = "Clarify"
    plan = Plan(intent="clarify", service="Clarify", tools=[])

    fake_gen = MagicMock()
    fake_gen.agenerate = AsyncMock(return_value="should not run")
    fake_provider = MagicMock()
    fake_provider.name = "ollama"
    fake_provider.config = LLMConfig(provider="ollama", model="qwen3:8b")
    fake_provider.supports_tools = MagicMock(return_value=False)
    fake_provider.close = AsyncMock()

    with (
        patch.object(svc, "_make_renderer", return_value=fake_gen),
        patch.object(svc._TEMPLATE, "generate", return_value="template answer") as tmpl,
        patch.object(svc._CALLER, "execute_plan", new=AsyncMock()) as exec_plan,
    ):
        text, tool_names, meta = asyncio.run(
            svc._run_planner_fallback(
                ctx,
                plan,
                backend="ollama",
                provider=fake_provider,
                reason="local_planner_first",
            )
        )

    assert text == "template answer"
    assert meta["used_backend"] == "template"
    assert meta["renderer_invoked"] is False
    assert "no_plan_tools" in meta["fallback_reason"]
    tmpl.assert_called_once()
    fake_gen.agenerate.assert_not_awaited()
    exec_plan.assert_not_awaited()
    assert tool_names == []


def test_planner_fallback_renderer_error_uses_template():
    """After ok ToolResult, renderer failure → template (no hallucinated expert reply)."""
    from bot.services.ghosteek_ai import service as svc
    from bot.services.ghosteek_ai.context.ai_context import AIContext
    from bot.services.ghosteek_ai.models import Plan, ToolResult, ToolSpec

    ctx = AIContext(raw_message="разбери колоду")
    ctx.intent.request = "analyze_deck"
    plan = Plan(
        intent="analyze_deck",
        service="DeckAnalyzer",
        tools=[ToolSpec(name="deck_analysis", args={})],
    )
    ok_result = ToolResult(tool="deck_analysis", ok=True, data={"score": 1})

    fake_gen = MagicMock()
    fake_gen.agenerate = AsyncMock(side_effect=RuntimeError("Ollama connection error"))
    fake_provider = MagicMock()
    fake_provider.name = "ollama"
    fake_provider.config = LLMConfig(provider="ollama", model="qwen3:8b")
    fake_provider.supports_tools = MagicMock(return_value=False)

    with (
        patch.object(svc, "_make_renderer", return_value=fake_gen),
        patch.object(svc._TEMPLATE, "generate", return_value="template answer") as tmpl,
        patch.object(svc._CALLER, "execute_plan", new=AsyncMock(return_value=[ok_result])),
    ):
        text, tool_names, meta = asyncio.run(
            svc._run_planner_fallback(
                ctx,
                plan,
                backend="ollama",
                provider=fake_provider,
                reason="local_planner_first",
            )
        )

    assert text == "template answer"
    assert meta["used_backend"] == "template"
    assert meta["renderer_invoked"] is False
    assert meta["tool_success"] is True
    assert "Ollama connection error" in meta["fallback_reason"]
    tmpl.assert_called_once()
    fake_gen.agenerate.assert_awaited_once()
    assert tool_names == ["deck_analysis"]


def test_ollama_auto_mode_resolves_to_planner_when_tools_disabled():
    from bot.services.ghosteek_ai import service as svc

    provider = OllamaProvider(
        LLMConfig(provider="ollama", model="qwen3:8b", extra={"enable_tools": False})
    )
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="ollama") == "planner"
