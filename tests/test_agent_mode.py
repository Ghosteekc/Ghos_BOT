"""Tests for Agent Mode / Planner Mode resolution and agent loop."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.ghosteek_ai.agent.runner import run_llm_agent
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.base import LLMConfig
from bot.services.ghosteek_ai.llm.messages import LLMGenerateResult, LLMToolCall
from bot.services.ghosteek_ai.llm.provider import OllamaProvider
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool, ToolCaller, ToolRegistry


def test_ollama_supports_tools_from_config():
    """Renderer-first qwen3:8b: tools stay off even if enable_tools=true."""
    assert OllamaProvider(
        LLMConfig(provider="ollama", model="qwen3:8b", extra={"enable_tools": False})
    ).supports_tools() is False
    assert OllamaProvider(
        LLMConfig(provider="ollama", model="qwen3:8b", extra={"enable_tools": True})
    ).supports_tools() is False
    # Non-profile local model may enable tools via config.
    assert OllamaProvider(
        LLMConfig(provider="ollama", model="custom-local:7b", extra={"enable_tools": True})
    ).supports_tools() is True


def test_resolve_runtime_mode_cloud_auto_planner_agent_explicit():
    from bot.services.ghosteek_ai import service as svc
    from bot.services.ghosteek_ai.llm.base import LLMCapabilities

    provider = MagicMock()
    provider.supports_tools.return_value = True
    provider.capabilities.return_value = LLMCapabilities(
        tools=True, agent_loop=True, renderer=True
    )
    provider.config = MagicMock(extra={"enable_tools": True}, model="llama")
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="groq") == "planner"

    with patch.object(svc, "_configured_mode", return_value="agent"):
        assert svc._resolve_runtime_mode(provider, backend="groq") == "agent"

    provider.supports_tools.return_value = False
    provider.capabilities.return_value = LLMCapabilities(
        tools=False, agent_loop=False, renderer=False
    )
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="groq") == "planner"

    with patch.object(svc, "_configured_mode", return_value="planner"):
        assert svc._resolve_runtime_mode(provider, backend="groq") == "planner"


def test_run_llm_agent_executes_tool_then_final_text():
    ctx = AIContext(raw_message="разбери колоду")
    ctx.intent.request = "analyze_deck"
    ctx.intent.service = "DeckAnalyzer"

    provider = MagicMock()
    provider.supports_tools.return_value = True

    tool_call = LLMToolCall(id="call_1", name="clarify", arguments={})
    first = LLMGenerateResult(text="", tool_calls=[tool_call])
    second = LLMGenerateResult(text="Финальный ответ агента.")
    provider.generate = AsyncMock(side_effect=[first, second])

    class ClarifyTool(BaseTool):
        name = "clarify"
        description = "clarify"

        async def execute(self, ctx):
            return ToolResult(tool=self.name, ok=True, data={"prompt": "x"}, call_id="call_1")

    registry = ToolRegistry()
    registry.register(ClarifyTool())
    caller = ToolCaller(registry)

    result = asyncio.run(
        run_llm_agent(
            ctx,
            provider=provider,
            caller=caller,
            registry=registry,
            planner_plan=None,
        )
    )
    assert result.text == "Финальный ответ агента."
    assert result.tool_names == ["clarify"]
    assert result.used_tool_calling is True
    assert result.rounds == 2
    assert provider.generate.await_count == 2


def test_run_llm_agent_no_tools_blocked():
    """Без ToolResult финальный ответ запрещён → «Не удалось получить данные.»"""
    from bot.services.ghosteek_ai.tools.llm_round import NO_DATA_USER_MESSAGE

    ctx = AIContext(raw_message="привет")
    provider = MagicMock()
    provider.supports_tools.return_value = True
    # Модель упорно отвечает текстом без tool_calls.
    provider.generate = AsyncMock(
        return_value=LLMGenerateResult(text="Привет! Чем помочь?")
    )

    class ClarifyTool(BaseTool):
        name = "clarify"
        description = "clarify"

        async def execute(self, ctx):
            return ToolResult(tool=self.name, ok=True, data={})

    registry = ToolRegistry()
    registry.register(ClarifyTool())
    caller = ToolCaller(registry)

    result = asyncio.run(
        run_llm_agent(
            ctx,
            provider=provider,
            caller=caller,
            registry=registry,
            max_tool_rounds=2,
        )
    )
    assert result.text == NO_DATA_USER_MESSAGE
    assert result.used_tool_calling is False
    assert result.tool_names == []
    assert provider.generate.await_count == 2


def test_run_llm_agent_failed_tool_blocked():
    """Tool ok=False → финальный ответ модели блокируется."""
    from bot.services.ghosteek_ai.tools.llm_round import NO_DATA_USER_MESSAGE

    ctx = AIContext(raw_message="разбери колоду")
    provider = MagicMock()
    provider.supports_tools.return_value = True

    tool_call = LLMToolCall(id="call_1", name="deck_analysis", arguments={})
    first = LLMGenerateResult(text="", tool_calls=[tool_call])
    second = LLMGenerateResult(text="Вот анализ колоды из головы.")
    provider.generate = AsyncMock(side_effect=[first, second])

    class FailTool(BaseTool):
        name = "deck_analysis"
        description = "fail"

        async def execute(self, ctx):
            return ToolResult(
                tool=self.name,
                ok=False,
                error_code="DECK_MISSING",
                call_id="call_1",
            )

    registry = ToolRegistry()
    registry.register(FailTool())
    caller = ToolCaller(registry)

    result = asyncio.run(
        run_llm_agent(
            ctx,
            provider=provider,
            caller=caller,
            registry=registry,
        )
    )
    assert result.text == NO_DATA_USER_MESSAGE
    assert result.tool_names == ["deck_analysis"]
    assert result.used_tool_calling is True


def test_planner_meta_stats_map_to_clarify():
    from bot.services.ghosteek_ai.intents import INTENT_META, INTENT_STATS
    from bot.services.ghosteek_ai.planner.planner import INTENT_TOOL_MAP, Planner
    from bot.services.ghosteek_ai.tools.base import build_default_registry

    assert INTENT_TOOL_MAP[INTENT_META] == ["clarify"]
    assert INTENT_TOOL_MAP[INTENT_STATS] == ["clarify"]
    names = {t["name"] for t in build_default_registry().catalog()}
    assert "meta" not in names
    assert "stats" not in names
    p = Planner(build_default_registry())
    assert p.select_tool_names(INTENT_META) == ["clarify"]
    assert p.select_tool_names(INTENT_STATS) == ["clarify"]
