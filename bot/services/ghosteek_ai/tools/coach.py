"""Tool: Game Coach — climb tips / archetype matchup."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.game_coach import CLIMB_TIPS, resolve_archetype_deck
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.deps import call_resolve_player_deck
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema
from bot.services.matchup_evaluation import evaluate_matchup


class GameCoachTool(BaseTool):
    name = "game_coach"
    description = (
        "Coaching tips: climb trophies, or how to play vs a named archetype "
        "(uses curated META_DECKS + matchup evaluation)."
    )
    input_schema = object_schema(
        {
            "coach_topic": COMMON_INPUT_PROPERTIES["coach_topic"],
            "cards": COMMON_INPUT_PROPERTIES["cards"],
            "raw": COMMON_INPUT_PROPERTIES["raw"],
        },
    )

    async def execute(self, ctx: AIContext) -> ToolResult:
        topic = ctx.intent.coach_topic or ctx.arg("coach_topic") or "general"
        raw = ctx.raw_message or ctx.arg("raw") or ""

        if topic == "climb":
            return ToolResult(
                tool=self.name,
                ok=True,
                data={"topic": "climb", "tips": list(CLIMB_TIPS)},
                actions=[
                    {"type": "navigate", "path": "/battles"},
                    {"type": "navigate", "path": "/analytics"},
                ],
            )

        arch = resolve_archetype_deck(str(raw))
        if arch is None and topic == "vs_advice":
            return ToolResult(
                tool=self.name,
                ok=False,
                error_code="COACH_NEED_ARCHETYPE",
            )

        if arch is not None:
            user = ctx.require_user()
            arch_name, opp_deck = arch
            user_deck = await call_resolve_player_deck(user, ctx.cards_arg())
            if len(user_deck) < 8:
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    error_code="COACH_NEED_DECK",
                    error_params={"archetype": arch_name},
                    data={"archetype": arch_name, "opponent_deck": opp_deck},
                    actions=[{"type": "navigate", "path": "/decks/compare"}],
                )
            evaluation = evaluate_matchup(user_deck[:8], opp_deck)
            return ToolResult(
                tool=self.name,
                ok=True,
                data={
                    "topic": "vs_advice",
                    "archetype": arch_name,
                    "user_deck": user_deck[:8],
                    "opponent_deck": opp_deck,
                    "score": evaluation.score,
                    "rating": evaluation.rating,
                    "reasons": evaluation.reasons,
                    "advantages": evaluation.advantages,
                    "disadvantages": evaluation.disadvantages,
                    "tips": [
                        "Оценка — по эталонной колоде этого архетипа.",
                        "Свой последний бой с таким соперником разберём отдельно.",
                    ],
                },
                actions=[{"type": "navigate", "path": "/decks/compare"}],
            )

        return ToolResult(
            tool=self.name,
            ok=False,
            error_code="COACH_CLARIFY",
        )
