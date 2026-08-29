"""Context Builder — создаёт и обновляет единый AIContext."""

from __future__ import annotations

from typing import Any

from bot.models.database import User
from bot.services.ghosteek_ai.context.ai_context import (
    AIContext,
    ArenaContext,
    BattleContext,
    ConversationContext,
    DeckContext,
    EvaluationContext,
    GamePlanContext,
    HistoryContext,
    IntentContext,
    KnowledgeContext,
    MetaContext,
    PlayerContext,
    RecommendationContext,
    SessionContext,
)
from bot.services.ghosteek_ai.conversation.state import ConversationState
from bot.services.ghosteek_ai.models import Plan, ToolResult


class ContextBuilder:
    """Bootstrap AIContext до tools и merge результатов после tools."""

    @staticmethod
    def bootstrap(
        *,
        user: User,
        plan: Plan,
        conversation: ConversationState,
        request_context: dict[str, Any] | None = None,
        raw_message: str = "",
        tool_args: dict[str, Any] | None = None,
    ) -> AIContext:
        req = dict(request_context or {})
        args = dict(tool_args or {})

        cards = _str_list(args.get("cards")) or _str_list(req.get("cards"))
        is_build = str(plan.intent or "") == "build_deck"
        if is_build:
            # Ядро сборки 1–4 карт — никогда не подменять полной last_deck.
            if not cards and getattr(conversation, "last_build_core", None):
                cards = list(conversation.last_build_core)[:4]
            elif len(cards) >= 8 and getattr(conversation, "last_build_core", None):
                core = list(conversation.last_build_core)[:4]
                if core and set(core).issubset(set(cards)):
                    cards = core
        elif len(cards) < 8 and len(conversation.last_deck) >= 8:
            cards = list(conversation.last_deck)

        opp = _str_list(args.get("opponent_cards")) or _str_list(req.get("opponent_cards"))
        if len(opp) < 8 and len(conversation.last_opponent_deck) >= 8:
            opp = list(conversation.last_opponent_deck)

        battle_index = args.get("battle_index", req.get("battle_index"))
        if battle_index is None:
            battle_index = conversation.last_battle_index

        followups = [
            {"kind": f.kind, "detail": f.detail, "intent": f.intent}
            for f in conversation.followups[-10:]
        ]

        battle = BattleContext()
        if conversation.last_battle:
            battle = BattleContext.from_data(dict(conversation.last_battle))
        if isinstance(battle_index, int):
            battle.battle_index = battle_index

        rec = RecommendationContext()
        if conversation.last_recommendation:
            rec.payload = dict(conversation.last_recommendation)

        ctx = AIContext(
            player=PlayerContext(
                telegram_id=user.telegram_id,
                tag=user.player_tag,
                name=getattr(user, "player_name", None),
            ),
            arena=ArenaContext(
                arena_id=getattr(user, "arena_id", None),
                trophies=getattr(user, "trophies", None),
            ),
            deck=DeckContext(cards=cards[:8], opponent_cards=opp[:8]),
            battle=battle,
            recommendation=rec,
            evaluation=EvaluationContext(),
            intent=IntentContext(
                request=plan.intent,
                service=plan.service,
                card_query=args.get("card_query"),
                mechanic_query=args.get("mechanic_query"),
                coach_topic=args.get("coach_topic"),
            ),
            game_plan=GamePlanContext(),
            session=SessionContext(
                public=conversation.to_public(),
                last_deck=list(conversation.last_deck),
                last_opponent_deck=list(conversation.last_opponent_deck),
                last_build_core=list(getattr(conversation, "last_build_core", None) or []),
                last_build_shown=[
                    list(d) for d in (getattr(conversation, "last_build_shown", None) or [])
                    if isinstance(d, list)
                ],
                last_battle_index=conversation.last_battle_index,
                last_battle=dict(conversation.last_battle),
                last_recommendation=dict(conversation.last_recommendation),
                active_topic=conversation.active_topic,
                last_intent=conversation.last_intent,
            ),
            conversation=ConversationContext(
                summary=conversation.summary or "",
                recent_messages=conversation.recent_messages_public(limit=6),
                last_questions=list(conversation.last_questions[-10:]),
                last_tools=list(conversation.last_tools[-10:]),
                followups=followups,
                active_topic=conversation.active_topic,
            ),
            knowledge=KnowledgeContext(),
            meta=MetaContext(),
            history=HistoryContext(
                summary=conversation.summary or "",
                turns=conversation.recent_messages_public(limit=6),
                last_analysis=dict(conversation.last_analysis),
            ),
            raw_message=raw_message,
            tool_args=args,
            request_context=req,
            _user=user,
        )
        return ctx

    @staticmethod
    def apply_tool_result(ctx: AIContext, result: ToolResult) -> AIContext:
        """Влить structured ToolResult в AIContext (без текста)."""
        ctx.tool_outputs[result.tool] = result.to_dict()
        for a in result.actions:
            if a not in ctx.actions:
                ctx.actions.append(a)

        ctx.ok = bool(result.ok)
        ctx.error_code = None if result.ok else result.error_code
        ctx.error_params = dict(result.error_params or {})
        data = dict(result.data or {})
        ctx.data = data

        # Deck
        for key in ("deck", "user_deck"):
            val = data.get(key)
            if isinstance(val, list) and len(val) >= 8:
                ctx.deck.cards = [c for c in val if isinstance(c, str)][:8]
                break
        opp = data.get("opponent_deck")
        if isinstance(opp, list) and len(opp) >= 8:
            ctx.deck.opponent_cards = [c for c in opp if isinstance(c, str)][:8]
        core = data.get("core")
        if isinstance(core, list):
            ctx.deck.core = [c for c in core if isinstance(c, str)]
        if isinstance(data.get("decks"), list):
            ctx.deck.built_decks = list(data["decks"])
            ctx.deck.build_mode = data.get("mode")

        # Structured DeckCard for UI (from Builder entry — no recompute)
        deck_card = data.get("deck_card")
        if isinstance(deck_card, dict) and deck_card.get("deck"):
            ctx.deck_card = dict(deck_card)
        elif result.tool == "deck_builder" and result.ok:
            from bot.services.ghosteek_ai.deck_card import (
                deck_card_from_build_data,
                format_arena_label,
            )

            built = deck_card_from_build_data(
                data,
                arena=format_arena_label(ctx.arena.arena_id, ctx.arena.trophies),
            )
            if built:
                ctx.deck_card = built
                data["deck_card"] = built
                ctx.data = data

        # Recommendation / GamePlan / DeckIntent
        rec = data.get("recommendation")
        if isinstance(rec, dict):
            ctx.recommendation.payload = rec
            di = rec.get("intent")
            if isinstance(di, dict):
                ctx.intent.deck_intent = di
            gp = rec.get("game_plan")
            if isinstance(gp, dict):
                ctx.game_plan.payload = gp
            plan = rec.get("improvement_plan") or {}
            if isinstance(plan, dict) and "needed" in plan:
                ctx.recommendation.improvement_needed = bool(plan.get("needed"))
        if "synergy_score" in data:
            ctx.recommendation.synergy_score = data.get("synergy_score")
        notes = data.get("synergy_notes")
        if isinstance(notes, list):
            ctx.recommendation.synergy_notes = list(notes)

        # Evaluation (matchup / coach vs)
        if any(k in data for k in ("score", "rating", "advantages", "disadvantages")):
            if result.tool in {"matchup", "game_coach"} or ctx.intent.request in {
                "matchup",
                "game_coach",
            }:
                ctx.evaluation = EvaluationContext.from_data(data)

        # Battle
        if result.tool == "battle_analysis" or ctx.intent.request == "last_battle":
            if data:
                ctx.battle = BattleContext.from_data(data)

        # Knowledge
        if result.tool in {"knowledge", "mechanics"}:
            ctx.knowledge.mechanic = dict(data)
        if result.tool == "card_info" and result.ok:
            ctx.knowledge.card = dict(data)
        if result.tool == "game_coach":
            ctx.knowledge.coach = dict(data)

        # Meta / stats stubs
        if result.tool == "meta":
            ctx.meta = MetaContext(
                ready=bool(result.ok),
                data=dict(data),
                error_code=result.error_code,
            )
        if result.tool == "stats" and not result.ok:
            ctx.meta.error_code = result.error_code

        return ctx

    @staticmethod
    def build(
        *,
        user: User,
        plan: Plan,
        conversation: ConversationState,
        tool_results: list[ToolResult],
        request_context: dict[str, Any] | None = None,
        raw_message: str = "",
        tool_args: dict[str, Any] | None = None,
    ) -> AIContext:
        """Полный цикл: bootstrap + apply всех tool results (совместимость)."""
        args = tool_args
        if args is None and plan.tools:
            args = dict(plan.tools[0].args)
        ctx = ContextBuilder.bootstrap(
            user=user,
            plan=plan,
            conversation=conversation,
            request_context=request_context,
            raw_message=raw_message,
            tool_args=args,
        )
        if not tool_results:
            ctx.ok = False
            ctx.error_code = "CLARIFY"
            return ctx

        primary = tool_results[0]
        for tr in tool_results:
            ContextBuilder.apply_tool_result(ctx, tr)
            if tr.ok:
                primary = tr
        # Финальный primary (успешный или первый)
        ContextBuilder.apply_tool_result(ctx, primary)
        return ctx


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [c for c in value if isinstance(c, str)]
