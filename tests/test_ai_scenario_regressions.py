"""Scenario regressions for Ghosteek AI's grounded orchestration.

These tests intentionally use structured ``ToolResult`` fixtures and tiny local
tools.  They must not call an LLM, player account, database, or game engine.
"""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.context.builder import ContextBuilder
from bot.services.ghosteek_ai.conversation.manager import ConversationManager
from bot.services.ghosteek_ai.conversation.state import ConversationState
from bot.services.ghosteek_ai.generator.response import TemplateResponseGenerator
from bot.services.ghosteek_ai.intents import (
    INTENT_ANALYZE_DECK,
    INTENT_CLARIFY,
    INTENT_IMPROVE_DECK,
    DetectedIntent,
    detect_intent,
)
from bot.services.ghosteek_ai.llm.local_renderer import attach_render_facts
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.planner.planner import Planner
from bot.services.ghosteek_ai.safety.layer import SafetyLayer
from bot.services.ghosteek_ai.safety.local_renderer_validator import (
    LOCAL_RENDERER_INVALID_FALLBACK,
    apply_local_renderer_gate,
)
from tests.fixtures.local_renderer_toolresults import (
    HOG_CYCLE,
    fixture_deck_analysis,
    fixture_recommendation,
)


def _ctx(intent: str, *, raw_message: str = "тест") -> AIContext:
    ctx = AIContext(raw_message=raw_message)
    ctx.intent.request = intent
    return ctx


def _apply(ctx: AIContext, result: ToolResult) -> AIContext:
    return ContextBuilder.apply_tool_result(ctx, result)


def test_deck_analysis_scenario_preserves_original_deck() -> None:
    """Analysis chooses the analysis tool and does not turn into a deck edit."""
    original = list(HOG_CYCLE)
    detected = DetectedIntent(INTENT_ANALYZE_DECK, cards=list(original), raw="разбери колоду")

    plan = Planner.plan(detected)
    assert [tool.name for tool in plan.tools] == ["deck_analysis"]

    ctx = _apply(_ctx(plan.intent), fixture_deck_analysis())
    assert ctx.ok is True
    assert ctx.deck.cards == original
    assert ctx.data["deck"] == original
    assert "improved_deck" not in ctx.data
    assert original == HOG_CYCLE


def test_explicit_improve_scenario_keeps_original_as_session_deck() -> None:
    """Recommendation may expose a proposal, but conversation state keeps input deck."""
    original = list(HOG_CYCLE)
    detected = DetectedIntent(INTENT_IMPROVE_DECK, cards=list(original), raw="улучши колоду")
    plan = Planner.plan(detected)
    assert [tool.name for tool in plan.tools] == ["recommendation"]

    result = fixture_recommendation()
    ctx = _apply(_ctx(plan.intent), result)
    assert ctx.data["original_deck"] == original
    assert ctx.data["improved_deck"] != original

    session = ConversationState()
    ConversationManager.update_from_ai_context(
        session,
        intent=plan.intent,
        service=plan.service,
        data=ctx.data,
        ok=True,
    )
    assert session.last_deck == original
    assert session.last_deck != ctx.data["improved_deck"]
    assert original == HOG_CYCLE


def test_insufficient_deck_data_returns_template_clarification() -> None:
    """No synthetic deck facts are rendered when the analysis tool lacks eight cards."""
    detected = detect_intent("разбери колоду")
    assert detected.intent == INTENT_ANALYZE_DECK
    assert detected.cards == []

    ctx = _apply(
        _ctx(detected.intent, raw_message="разбери колоду"),
        ToolResult(tool="deck_analysis", ok=False, error_code="NEED_DECK_8"),
    )
    assert ctx.ok is False
    assert ctx.data == {}
    answer = TemplateResponseGenerator().generate(ctx)
    assert "колод" in answer.lower()
    envelope = attach_render_facts(ctx)
    assert envelope["data"]["facts"] == []
    assert (
        apply_local_renderer_gate("Колода выглядит сильной.", envelope)
        == LOCAL_RENDERER_INVALID_FALLBACK
    )


def test_small_statistical_sample_is_clarified_not_presented_as_winrate() -> None:
    """Stats are not a stage-1 fact source, including a tempting two-game sample."""
    detected = detect_intent("какой винрейт за 2 боя?")
    assert detected.intent == INTENT_CLARIFY
    assert [tool.name for tool in Planner.plan(detected).tools] == ["clarify"]

    # Even if text tries to promote the sample to a statistic, no ToolResult
    # supplied a winrate, therefore SafetyLayer removes the exact claim.
    ctx = _ctx(INTENT_CLARIFY)
    ctx.data = {"sample_size": 2}
    answer = SafetyLayer.apply("По 2 боям винрейт 100% — это точная статистика.", ctx)
    assert "100%" not in answer
    assert "точная статистика" not in answer.lower()


def test_new_topic_does_not_inherit_previous_deck() -> None:
    session = ConversationState(last_deck=list(HOG_CYCLE), active_topic="analyze_deck")
    detected = detect_intent("Чем контрить Голема?")
    enriched = ConversationManager.apply_followup_enrichment(
        session, detected, "Чем контрить Голема?", {}
    )
    assert enriched.cards == ["Golem"]
    assert enriched.cards != HOG_CYCLE


def test_explicit_followup_reuses_only_the_previous_deck() -> None:
    session = ConversationState(last_deck=list(HOG_CYCLE))
    detected = detect_intent("Разбери мою колоду")
    enriched = ConversationManager.apply_followup_enrichment(
        session, detected, "Разбери мою колоду", {}
    )
    assert enriched.intent == INTENT_ANALYZE_DECK
    assert enriched.cards == HOG_CYCLE
    assert session.followups[-1].kind == "reuse_deck"


def test_fact_lock_rejects_unconfirmed_card_number_and_battle_event() -> None:
    """A renderer cannot promote a made-up replay claim into a game fact."""
    ctx = _apply(_ctx("last_battle"), ToolResult(
        tool="battle_analysis",
        ok=True,
        data={"won": False, "reasons": ["Рано атаковал"]},
    ))
    envelope = attach_render_facts(ctx)
    claim = "Wizard нанёс 900 урона на 30 секунде и принёс победу."
    assert apply_local_renderer_gate(claim, envelope) == LOCAL_RENDERER_INVALID_FALLBACK

    # The cloud/template path must also neutralize unsupported precise events.
    cloud = SafetyLayer.apply(claim, AIContext())
    assert "900" not in cloud
    assert "30 секунд" not in cloud.lower()


def test_tool_error_uses_safe_fallback_without_provider() -> None:
    """Tool failures stay structured and are rendered by the local safe fallback."""
    result = ToolResult(
        tool="synthetic_failing_tool",
        ok=False,
        error_code="SYNTHETIC_FAILURE",
        call_id="synthetic",
    )
    ctx = _apply(_ctx(INTENT_ANALYZE_DECK), result)
    assert result.ok is False
    assert result.error_code == "SYNTHETIC_FAILURE"
    assert ctx.ok is False
    assert ctx.error_code == "SYNTHETIC_FAILURE"

    envelope = attach_render_facts(ctx)
    assert envelope["data"]["facts"] == []
    assert SafetyLayer.apply("Deck looks perfect.", ctx) == LOCAL_RENDERER_INVALID_FALLBACK
