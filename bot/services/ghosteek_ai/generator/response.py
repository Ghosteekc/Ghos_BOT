"""Template Response Generator — голос через voice_templates.

Получает только AIContext. Не знает, как работают доменные сервисы.
Не трогает Builder / RecommendationEngine / Battle / Matchup engines.
"""

from __future__ import annotations

from typing import Any

from bot.services.ghosteek_ai.constraints import refuse_unsupported
from bot.services.ghosteek_ai.intents import (
    CLARIFY_PROMPT,
    INTENT_ANALYZE_DECK,
    INTENT_BUILD_DECK,
    INTENT_CARD_INFO,
    INTENT_EXPLAIN_MECHANIC,
    INTENT_GAME_COACH,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    INTENT_MATCHUP,
)
from bot.services.ghosteek_ai.models import AIContext
from bot.services.ghosteek_ai.voice import assert_coach_voice, coach_reply, trim_to_word_limit, word_limit_for
from bot.services.ghosteek_ai.voice_templates import (
    template_analyze_deck,
    template_battle,
    template_build_deck,
    template_card_info,
    template_error,
    template_game_coach,
    template_mechanic,
    template_matchup,
)


def _truncate_q(text: str, limit: int = 64) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


class TemplateResponseGenerator:
    """Генерация ответа из AIContext через intent-шаблоны голоса."""

    backend = "template"

    def generate(self, ctx: AIContext) -> str:
        if not ctx.ok:
            return assert_coach_voice(self._from_error(ctx))
        text = self._from_success(ctx)
        return assert_coach_voice(text)

    async def agenerate(self, ctx: AIContext) -> str:
        return self.generate(ctx)

    def _from_error(self, ctx: AIContext) -> str:
        code = ctx.error_code or "CLARIFY"
        params = ctx.error_params or {}

        if code == "UNSUPPORTED":
            return refuse_unsupported()

        if code in {"CLARIFY", "META_NOT_READY", "STATS_NOT_READY"}:
            return self._clarify_with_memory(ctx)

        mapped = template_error(code, params if isinstance(params, dict) else {})
        if mapped:
            return mapped

        return assert_coach_voice(CLARIFY_PROMPT)

    def _clarify_with_memory(self, ctx: AIContext) -> str:
        prev_questions = list(ctx.last_questions[:-1]) if ctx.last_questions else []
        if ctx.conversation_summary or prev_questions:
            why = ""
            if prev_questions:
                last_q = prev_questions[-1]
                if last_q and last_q.strip():
                    why = f"Ранее: «{_truncate_q(last_q)}»."
            return coach_reply(
                "Уточни одну цель.",
                why=why or "Без конкретики совет будет общим.",
                tip="Колода, матчап, бой, карта или термин — выбери одно.",
                intent="clarify",
            )
        return assert_coach_voice(CLARIFY_PROMPT)

    def _from_success(self, ctx: AIContext) -> str:
        intent = ctx.intent.request
        data = ctx.primary_tool_data()

        if intent == INTENT_CARD_INFO:
            text = template_card_info(ctx.knowledge.card or data)
        elif intent == INTENT_EXPLAIN_MECHANIC:
            text = template_mechanic(ctx.knowledge.mechanic or data)
        elif intent == INTENT_GAME_COACH:
            text = template_game_coach(ctx.knowledge.coach or data)
        elif intent == INTENT_ANALYZE_DECK:
            text = template_analyze_deck(data, improve=False)
        elif intent == INTENT_IMPROVE_DECK:
            text = template_analyze_deck(data, improve=True)
        elif intent == INTENT_BUILD_DECK:
            text = template_build_deck(ctx.build or data)
        elif intent == INTENT_LAST_BATTLE:
            battle = ctx.battle.to_dict() if (ctx.battle.raw or ctx.battle.opponent_name) else data
            text = template_battle(battle)
        elif intent == INTENT_MATCHUP:
            eval_data = ctx.evaluation.to_dict()
            merged = (
                {**eval_data, **data}
                if eval_data.get("rating") or eval_data.get("score") is not None
                else data
            )
            text = template_matchup(merged)
        else:
            text = coach_reply(
                "Уточни задачу.",
                tip="Колода, матчап, бой или термин — выбери одно.",
                intent="clarify",
            )

        return trim_to_word_limit(text, word_limit_for(intent))


# Singleton для оркестратора / тестов
_default_generator = TemplateResponseGenerator()

# Alias по ТЗ
TemplateGenerator = TemplateResponseGenerator


def generate_response(ctx: AIContext) -> str:
    """Совместимый entrypoint: всегда Template."""
    from bot.services.ghosteek_ai.generator.factory import get_response_generator

    return get_response_generator("template").generate(ctx)


def compose_answer_from_payload(payload: dict[str, Any]) -> str:
    """Совместимость со старым compose_answer(payload) для тестов."""
    from bot.services.ghosteek_ai.context.ai_context import (
        BattleContext,
        EvaluationContext,
        IntentContext,
        KnowledgeContext,
        RecommendationContext,
    )
    from bot.services.ghosteek_ai.context.builder import ContextBuilder
    from bot.services.ghosteek_ai.models import ToolResult

    intent = str(payload.get("intent") or "")
    ok = bool(payload.get("ok"))
    data = payload.get("data") or {}
    error = payload.get("error")

    if not ok:
        if isinstance(error, str) and error.strip():
            return assert_coach_voice(error)
        ctx = AIContext(
            intent=IntentContext(request=intent, service=""),
            ok=False,
            data=data,
            error_code="CLARIFY",
        )
        return _default_generator.generate(ctx)

    ctx = AIContext(
        intent=IntentContext(request=intent, service=""),
        ok=True,
        data=data,
        knowledge=KnowledgeContext(),
        recommendation=RecommendationContext(),
    )
    result = ToolResult(tool=intent or "tool", ok=True, data=data)
    ContextBuilder.apply_tool_result(ctx, result)

    if intent == INTENT_CARD_INFO:
        ctx.knowledge.card = dict(data)
    elif intent == INTENT_EXPLAIN_MECHANIC:
        ctx.knowledge.mechanic = dict(data)
    elif intent == INTENT_GAME_COACH:
        ctx.knowledge.coach = dict(data)
    elif intent == INTENT_LAST_BATTLE:
        ctx.battle = BattleContext.from_data(data)
    elif intent == INTENT_MATCHUP:
        ctx.evaluation = EvaluationContext.from_data(data)
    elif intent in {INTENT_ANALYZE_DECK, INTENT_IMPROVE_DECK}:
        rec = data.get("recommendation")
        if isinstance(rec, dict):
            ctx.recommendation.payload = rec
        ctx.recommendation.synergy_score = data.get("synergy_score")
        notes = data.get("synergy_notes")
        if isinstance(notes, list):
            ctx.recommendation.synergy_notes = list(notes)
    elif intent == INTENT_BUILD_DECK:
        core = data.get("core")
        if isinstance(core, list):
            ctx.deck.core = [c for c in core if isinstance(c, str)]
        if isinstance(data.get("decks"), list):
            ctx.deck.built_decks = list(data["decks"])
            ctx.deck.build_mode = data.get("mode")

    return _default_generator.generate(ctx)
