"""Planner-first for local Ollama qwen3:8b — LLM only after successful ToolResult."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.ghosteek_ai.llm.base import LLMConfig
from bot.services.ghosteek_ai.llm.provider import OllamaProvider
from bot.services.ghosteek_ai.models import Plan, ToolResult, ToolSpec


def _ctx(intent: str = "analyze_deck"):
    from bot.services.ghosteek_ai.context.ai_context import AIContext

    ctx = AIContext(raw_message="разбери колоду")
    ctx.intent.request = intent
    ctx.intent.service = "DeckAnalyzer"
    return ctx


def test_a_deck_analysis_success_invokes_renderer():
    """A: intent=deck_analysis → tool runs → LLM gets ToolResult path → response."""
    from bot.services.ghosteek_ai import service as svc

    ctx = _ctx("analyze_deck")
    plan = Plan(
        intent="analyze_deck",
        service="DeckAnalyzer",
        tools=[ToolSpec(name="deck_analysis", args={"cards": ["Hog Rider"]})],
    )
    ok_result = ToolResult(
        tool="deck_analysis",
        ok=True,
        data={"verdict": "ok", "cards": ["Hog Rider"]},
    )

    fake_gen = MagicMock()
    fake_gen.agenerate = AsyncMock(return_value="Rendered from ToolResult.")
    provider = MagicMock()
    provider.name = "ollama"
    provider.config = LLMConfig(provider="ollama", model="qwen3:8b")
    provider.supports_tools = MagicMock(return_value=False)

    with (
        patch.object(svc, "_make_renderer", return_value=fake_gen) as make_r,
        patch.object(svc._TEMPLATE, "generate", return_value="TEMPLATE") as tmpl,
        patch.object(
            svc._CALLER, "execute_plan", new=AsyncMock(return_value=[ok_result])
        ) as exec_plan,
    ):
        text, tools, meta = asyncio.run(
            svc._run_planner_fallback(
                ctx,
                plan,
                backend="ollama",
                provider=provider,
                reason="local_planner_first",
            )
        )

    exec_plan.assert_awaited_once()
    make_r.assert_called_once()
    fake_gen.agenerate.assert_awaited_once()
    call_kwargs = fake_gen.agenerate.await_args
    assert call_kwargs.kwargs.get("tools") is None
    tmpl.assert_not_called()
    assert text == "Rendered from ToolResult."
    assert tools == ["deck_analysis"]
    assert meta["mode"] == "planner"
    assert meta["renderer_invoked"] is True
    assert meta["tool_success"] is True
    assert meta["used_backend"] == "ollama"


def test_b_deck_analysis_tool_fail_skips_llm():
    """B: tool fail → LLM NOT called → template."""
    from bot.services.ghosteek_ai import service as svc

    ctx = _ctx("analyze_deck")
    plan = Plan(
        intent="analyze_deck",
        service="DeckAnalyzer",
        tools=[ToolSpec(name="deck_analysis", args={})],
    )
    fail = ToolResult(tool="deck_analysis", ok=False, error_code="DECK_MISSING")

    fake_gen = MagicMock()
    fake_gen.agenerate = AsyncMock(return_value="hallucination")
    provider = MagicMock()
    provider.name = "ollama"
    provider.config = LLMConfig(provider="ollama", model="qwen3:8b")

    with (
        patch.object(svc, "_make_renderer", return_value=fake_gen),
        patch.object(svc._TEMPLATE, "generate", return_value="need deck") as tmpl,
        patch.object(svc._CALLER, "execute_plan", new=AsyncMock(return_value=[fail])),
    ):
        text, tools, meta = asyncio.run(
            svc._run_planner_fallback(
                ctx,
                plan,
                backend="ollama",
                provider=provider,
                reason="local_planner_first",
            )
        )

    fake_gen.agenerate.assert_not_awaited()
    tmpl.assert_called_once()
    assert text == "need deck"
    assert tools == ["deck_analysis"]
    assert meta["renderer_invoked"] is False
    assert meta["tool_success"] is False
    assert meta["used_backend"] == "template"
    assert "tool_failed_or_clarify" in meta["fallback_reason"]


def test_c_unknown_intent_skips_llm():
    """C: unknown / clarify / unsupported → LLM NOT called."""
    from bot.services.ghosteek_ai import service as svc
    from bot.services.ghosteek_ai.planner.planner import Planner

    # Unknown intent maps to clarify via INTENT_TOOL_MAP fallback.
    names = Planner().select_tool_names("totally_unknown_intent")
    assert names == ["clarify"]

    ctx = _ctx("clarify")
    plan = Plan(
        intent="clarify",
        service="Clarify",
        tools=[ToolSpec(name="clarify", args={})],
    )
    clarify = ToolResult(tool="clarify", ok=False, error_code="CLARIFY")

    fake_gen = MagicMock()
    fake_gen.agenerate = AsyncMock(return_value="hallucination")
    provider = MagicMock()
    provider.config = LLMConfig(provider="ollama", model="qwen3:8b")

    with (
        patch.object(svc, "_make_renderer", return_value=fake_gen),
        patch.object(svc._TEMPLATE, "generate", return_value="уточни") as tmpl,
        patch.object(svc._CALLER, "execute_plan", new=AsyncMock(return_value=[clarify])),
    ):
        text, tools, meta = asyncio.run(
            svc._run_planner_fallback(
                ctx,
                plan,
                backend="ollama",
                provider=provider,
                reason="local_planner_first",
            )
        )

    fake_gen.agenerate.assert_not_awaited()
    tmpl.assert_called_once()
    assert text == "уточни"
    assert tools == ["clarify"]
    assert meta["renderer_invoked"] is False
    assert meta["tool_success"] is False


def test_d_groq_coach_planner_by_default():
    """D: backend=groq auto → planner+LocalRenderer; explicit agent still Agent."""
    from bot.services.ghosteek_ai import service as svc

    provider = MagicMock()
    provider.supports_tools.return_value = True
    provider.config = LLMConfig(provider="groq", model="llama-3.3-70b")

    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="groq") == "planner"
        assert svc._force_planner_first("groq", provider) is True

    with patch.object(svc, "_configured_mode", return_value="agent"):
        assert svc._resolve_runtime_mode(provider, backend="groq") == "agent"
        assert svc._force_planner_first("groq", provider) is False

    assert svc._is_local_renderer_first("groq", provider) is False
    assert svc._is_local_qwen3_8b("groq", provider) is False
    assert svc._uses_coach_renderer("groq") is True
    assert svc._uses_coach_renderer("qwen") is True


def test_e_ollama_qwen3_8b_forces_planner_first():
    """E: backend=ollama + qwen3:8b → planner-first even if tools enabled / mode=agent."""
    from bot.services.ghosteek_ai import service as svc

    provider = OllamaProvider(
        LLMConfig(provider="ollama", model="qwen3:8b", extra={"enable_tools": True})
    )
    assert provider.supports_tools() is False
    assert svc._is_local_renderer_first("ollama", provider) is True
    assert svc._is_local_qwen3_8b("ollama", provider) is True
    assert svc._force_planner_first("ollama", provider) is True

    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="ollama") == "planner"

    with patch.object(svc, "_configured_mode", return_value="agent"):
        assert svc._resolve_runtime_mode(provider, backend="ollama") == "planner"

    # Alias backend=local
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="local") == "planner"


def test_intent_tool_map_unchanged_for_core_intents():
    """Do not invent new mappings — reuse existing INTENT_TOOL_MAP."""
    from bot.services.ghosteek_ai.intents import (
        INTENT_ANALYZE_DECK,
        INTENT_BUILD_DECK,
        INTENT_CARD_INFO,
        INTENT_EXPLAIN_MECHANIC,
        INTENT_GAME_COACH,
        INTENT_IMPROVE_DECK,
        INTENT_LAST_BATTLE,
        INTENT_MATCHUP,
    )
    from bot.services.ghosteek_ai.planner.planner import INTENT_TOOL_MAP

    assert INTENT_TOOL_MAP[INTENT_CARD_INFO] == ["card_info"]
    assert INTENT_TOOL_MAP[INTENT_BUILD_DECK] == ["deck_builder"]
    assert INTENT_TOOL_MAP[INTENT_ANALYZE_DECK] == ["deck_analysis"]
    assert INTENT_TOOL_MAP[INTENT_IMPROVE_DECK] == ["recommendation"]
    assert INTENT_TOOL_MAP[INTENT_MATCHUP] == ["matchup"]
    assert INTENT_TOOL_MAP[INTENT_LAST_BATTLE] == ["battle_analysis"]
    assert INTENT_TOOL_MAP[INTENT_EXPLAIN_MECHANIC] == ["knowledge"]
    assert INTENT_TOOL_MAP[INTENT_GAME_COACH] == ["game_coach"]


def test_ask_ghosteek_ai_ollama_uses_planner_not_agent():
    """End-to-end: ollama+qwen3:8b routes to planner path, not run_llm_agent."""
    from bot.services.ghosteek_ai import service as svc
    from bot.services.ghosteek_ai.models import GhosteekAiResponse

    user = MagicMock()
    user.telegram_id = 999001

    provider = OllamaProvider(
        LLMConfig(provider="ollama", model="qwen3:8b", extra={"enable_tools": True})
    )

    planner_meta = {
        "mode": "planner",
        "llm_backend": "ollama",
        "used_backend": "ollama",
        "response_time_ms": 1.0,
        "fallback_reason": "local_planner_first",
        "renderer_invoked": True,
        "tool_success": True,
        "model": "qwen3:8b",
    }

    with (
        patch.object(svc, "_configured_backend", return_value="ollama"),
        patch.object(svc, "_configured_mode", return_value="auto"),
        patch.object(svc, "_resolve_provider", return_value=provider),
        patch.object(
            svc,
            "_run_planner_fallback",
            new=AsyncMock(return_value=("ok", ["deck_analysis"], planner_meta)),
        ) as planner,
        patch.object(svc, "_run_agent_mode", new=AsyncMock()) as agent,
        patch.object(svc, "_sanity_blocks_explain", return_value=False),
        patch(
            "bot.services.ghosteek_ai.service.detect_intent",
            return_value=MagicMock(
                intent="analyze_deck",
                service="DeckAnalyzer",
                cards=[],
                battle_index=None,
                query="",
                mechanic=None,
                topic=None,
            ),
        ),
        patch(
            "bot.services.ghosteek_ai.service.ConversationManager.get_or_create",
            return_value=MagicMock(
                summary="",
                messages=[],
                last_questions=[],
                to_public=MagicMock(return_value={"summary_preview": ""}),
            ),
        ),
        patch(
            "bot.services.ghosteek_ai.service.ConversationManager.merge_request_context",
            return_value={},
        ),
        patch(
            "bot.services.ghosteek_ai.service.ConversationManager.apply_followup_enrichment",
            side_effect=lambda s, d, m, c: d,
        ),
        patch(
            "bot.services.ghosteek_ai.service.ConversationManager.add_user_message"
        ),
        patch(
            "bot.services.ghosteek_ai.service.ConversationManager.add_assistant_message"
        ),
        patch(
            "bot.services.ghosteek_ai.service.ConversationManager.update_from_ai_context"
        ),
        patch("bot.services.ghosteek_ai.service.ConversationManager.save"),
        patch(
            "bot.services.ghosteek_ai.service.Planner.plan",
            return_value=Plan(
                intent="analyze_deck",
                service="DeckAnalyzer",
                tools=[ToolSpec(name="deck_analysis")],
            ),
        ),
        patch(
            "bot.services.ghosteek_ai.service.ContextBuilder.bootstrap",
            return_value=_ctx("analyze_deck"),
        ),
        patch.object(svc.SafetyLayer, "apply", side_effect=lambda t, c: t),
    ):
        result = asyncio.run(svc.ask_ghosteek_ai("разбери колоду", user))

    planner.assert_awaited_once()
    agent.assert_not_awaited()
    assert isinstance(result, GhosteekAiResponse)
    assert result.sources["llm"]["mode"] == "planner"
    assert result.sources["llm"]["renderer_invoked"] is True
    assert result.sources["tools"] == ["deck_analysis"]
