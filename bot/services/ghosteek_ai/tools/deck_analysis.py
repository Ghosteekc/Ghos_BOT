"""Tool: Deck Analysis — RecommendationEngine without swaps."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.deps import (
    call_recommendation_analyze,
    call_resolve_player_deck,
)
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema


class DeckAnalysisTool(BaseTool):
    name = "deck_analysis"
    description = (
        "Analyze the player's 8-card deck: synergy, game plan, coaching. "
        "Does not apply card swaps (use recommendation for improvements)."
    )
    input_schema = object_schema({"cards": COMMON_INPUT_PROPERTIES["cards"]})

    async def execute(self, ctx: AIContext) -> ToolResult:
        user = ctx.require_user()
        deck = await call_resolve_player_deck(user, ctx.cards_arg())
        if len(deck) < 8:
            return ToolResult(
                tool=self.name,
                ok=False,
                error_code="NEED_DECK_8",
                actions=[{"type": "navigate", "path": "/decks"}],
            )
        rec = call_recommendation_analyze(deck, apply_swaps=False)
        evaluation = getattr(rec, "evaluation_report", None)
        synergy_score = (
            float(evaluation.synergy.score) if evaluation is not None else 0.0
        )
        synergy_notes = list(evaluation.synergy.notes) if evaluation is not None else []
        return ToolResult(
            tool=self.name,
            ok=True,
            data={
                "deck": deck,
                "recommendation": rec.to_public_dict(),
                "evaluation_report": evaluation.to_dict() if evaluation is not None else None,
                # Compat: synergy из EvaluationReport (Builder SoT), не отдельный калькулятор
                "synergy_score": synergy_score,
                "synergy_notes": synergy_notes,
            },
            actions=[{"type": "navigate", "path": "/decks"}],
        )
