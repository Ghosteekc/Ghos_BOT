"""Tool: Battle Analysis — structured battle report."""

from __future__ import annotations

from typing import Any

from bot.services.battle_report import analyze_battle_enhanced
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.deps import call_load_and_persist
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema


class BattleAnalysisTool(BaseTool):
    name = "battle_analysis"
    description = (
        "Analyze a recent Clash Royale battle for the linked player. "
        "Returns outcome, matchup score, reasons, match plan — no replay frames."
    )
    input_schema = object_schema(
        {"battle_index": COMMON_INPUT_PROPERTIES["battle_index"]},
    )

    async def execute(self, ctx: AIContext) -> ToolResult:
        user = ctx.require_user()
        battles = await call_load_and_persist(user)
        if not battles:
            return ToolResult(
                tool=self.name,
                ok=False,
                error_code="NO_BATTLES",
                actions=[{"type": "navigate", "path": "/battles"}],
            )

        index = ctx.arg("battle_index", ctx.battle.battle_index)
        if index is None:
            index = ctx.request_context.get("battle_index")
        if isinstance(index, int) and 0 <= index < len(battles):
            battle = battles[index]
            battle_index = index
        else:
            battle = battles[0]
            battle_index = 0

        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        duration = int(battle.get("gameDuration") or 0)
        analysis = analyze_battle_enhanced(team, opponent, duration=duration)

        data: dict[str, Any] = {
            "battle_index": battle_index,
            "won": analysis.won,
            "opponent_name": analysis.opponent_name,
            "matchup_score": analysis.matchup_score,
            "outcome_summary": analysis.outcome_summary,
            "reasons": analysis.reasons[:6],
            "evaluation_report": (
                analysis.evaluation_report.to_dict()
                if getattr(analysis, "evaluation_report", None) is not None
                else None
            ),
            "match_difficulty": (
                {
                    "difficulty": analysis.match_difficulty.difficulty,
                    "rating": analysis.match_difficulty.rating,
                    "reasons": analysis.match_difficulty.reasons[:4],
                }
                if analysis.match_difficulty
                else None
            ),
            "match_plan": (
                {
                    "win_condition_window": analysis.match_plan.win_condition_window,
                    "avoid": analysis.match_plan.avoid[:3],
                    "phase_1": analysis.match_plan.game_plan.phase_1[:2],
                }
                if analysis.match_plan
                else None
            ),
        }
        return ToolResult(
            tool=self.name,
            ok=True,
            data=data,
            actions=[{"type": "navigate", "path": f"/battles/{battle_index}"}],
        )
