"""Tool: Matchup — structured MatchupEvaluation."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.deps import call_load_and_persist, call_resolve_player_deck
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema
from bot.services.matchup_evaluation import evaluate_matchup


class MatchupTool(BaseTool):
    name = "matchup"
    description = (
        "Evaluate matchup between player deck and opponent deck "
        "(score, rating, advantages, disadvantages)."
    )
    input_schema = object_schema(
        {
            "cards": COMMON_INPUT_PROPERTIES["cards"],
            "opponent_cards": COMMON_INPUT_PROPERTIES["opponent_cards"],
        },
    )

    async def execute(self, ctx: AIContext) -> ToolResult:
        user = ctx.require_user()
        user_deck = await call_resolve_player_deck(user, ctx.cards_arg())
        opp = ctx.opponent_cards_arg()

        if len(opp) < 8:
            battles = await call_load_and_persist(user)
            if battles:
                opponent = battles[0].get("opponent", [{}])[0]
                opp = [c.get("name") for c in opponent.get("cards", []) if c.get("name")]
                if len(user_deck) < 8:
                    team = battles[0].get("team", [{}])[0]
                    user_deck = [
                        c.get("name") for c in team.get("cards", []) if c.get("name")
                    ]

        if len(user_deck) < 8 or len(opp) < 8:
            return ToolResult(
                tool=self.name,
                ok=False,
                error_code="MATCHUP_NEED_DECKS",
                actions=[{"type": "navigate", "path": "/battles"}],
            )

        from bot.services.deck_builder.quality import evaluate_deck

        matchup = evaluate_matchup(user_deck[:8], opp[:8])
        deck_report = evaluate_deck(user_deck[:8], opponent=opp[:8])
        return ToolResult(
            tool=self.name,
            ok=True,
            data={
                "user_deck": user_deck[:8],
                "opponent_deck": opp[:8],
                "score": matchup.score,
                "rating": matchup.rating,
                "reasons": matchup.reasons,
                "advantages": matchup.advantages,
                "disadvantages": matchup.disadvantages,
                "evaluation_report": deck_report.to_dict(),
            },
            actions=[{"type": "navigate", "path": "/decks/compare"}],
        )
