"""Tests for Agent Mode / Planner Mode resolution and agent loop."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.ghosteek_ai.agent.runner import run_llm_agent
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.messages import LLMGenerateResult, LLMToolCall
from bot.services.ghosteek_ai.llm.provider import OllamaProvider
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool, ToolCaller, ToolRegistry


def test_ollama_supports_tools_by_default():
    p = OllamaProvider()
    assert p.supports_tools() is True


def test_resolve_runtime_mode_auto_agent_when_tools():
    from bot.services.ghosteek_ai import service as svc

    provider = MagicMock()
    provider.supports_tools.return_value = True
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider) == "agent"

    provider.supports_tools.return_value = False
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider) == "planner"

    with patch.object(svc, "_configured_mode", return_value="planner"):
        assert svc._resolve_runtime_mode(provider) == "planner"


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


def test_run_llm_agent_no_tools_returns_immediately():
    ctx = AIContext(raw_message="привет")
    provider = MagicMock()
    provider.supports_tools.return_value = True
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
        )
    )
    assert result.text == "Привет! Чем помочь?"
    assert result.used_tool_calling is False
    assert result.rounds == 1
    assert provider.generate.await_count == 1
