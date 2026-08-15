"""ToolResult fixtures for Ghosteek AI local renderer regression tests.

Это LLM-facing / ToolResult shapes — не мок бизнес-логики RecommendationEngine.
"""

from __future__ import annotations

from typing import Any

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.local_renderer import (
    attach_render_facts,
    build_facts_envelope,
)
from bot.services.ghosteek_ai.models import ToolResult

HOG_CYCLE = [
    "Hog Rider",
    "Musketeer",
    "Ice Spirit",
    "Cannon",
    "Fireball",
    "Zap",
    "Skeletons",
    "Ice Golem",
]

EGOLEM_COUNTERS = [
    "Inferno Tower",
    "Mini P.E.K.K.A",
    "Inferno Dragon",
    "Executioner",
]


def tool_result(
    tool: str,
    *,
    ok: bool = True,
    data: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        ok=ok,
        data=dict(data or {}),
        error_code=error_code,
        call_id=f"call_{tool}",
    )


def fixture_card_info() -> ToolResult:
    return tool_result(
        "card_info",
        data={
            "name": "Elixir Golem",
            "name_ru": "Элик-Голем",
            "elixir": 3,
            "card_type": "troop",
            "roles": ["win_condition", "tank"],
        },
    )


def fixture_deck_analysis() -> ToolResult:
    return tool_result(
        "deck_analysis",
        data={
            "deck": list(HOG_CYCLE),
            "average_elixir": 2.6,
            "synergy_score": 72,
            "synergy_notes": ["Цикл держит темп"],
            "recommendation": {
                "intent": {"primary_win": "Hog Rider", "archetype": "Cycle"},
                "coaching": {
                    "strengths": ["Воздушная защита: Musketeer"],
                    "play_style": "cycle",
                },
                "game_plan": {
                    "critical_weaknesses": ["недостаточно anti-air"],
                    "how_to_win": "Цикли Хога",
                },
                "improvement_plan": {"needed": False, "steps": []},
            },
        },
    )


def fixture_deck_builder() -> ToolResult:
    deck = list(HOG_CYCLE)
    return tool_result(
        "deck_builder",
        data={
            "mode": "core",
            "core": ["Hog Rider"],
            "decks": [
                {
                    "name": "Hog Cycle",
                    "archetype": "Cycle",
                    "cards": deck,
                    "average_elixir": 2.6,
                }
            ],
            "deck_card": {
                "title": "Hog Cycle",
                "archetype": "Cycle",
                "average_elixir": 2.6,
                "cards": deck,
            },
        },
    )


def fixture_recommendation() -> ToolResult:
    return tool_result(
        "recommendation",
        data={
            "deck": list(HOG_CYCLE),
            "original_deck": list(HOG_CYCLE),
            "improved_deck": [
                "Hog Rider",
                "Musketeer",
                "Electro Spirit",
                "Cannon",
                "Fireball",
                "Zap",
                "Skeletons",
                "Ice Golem",
            ],
            "average_elixir": 2.6,
            "synergy_score": 74,
            "recommendation": {
                "intent": {"primary_win": "Hog Rider"},
                "coaching": {"strengths": ["Хог давит"], "play_style": "cycle"},
                "game_plan": {"critical_weaknesses": ["слабый reset"]},
                "improvement_plan": {
                    "needed": True,
                    "steps": [
                        {
                            "drop": "Ice Spirit",
                            "pick": "Electro Spirit",
                            "message": "Ice Spirit → Electro Spirit для reset",
                        }
                    ],
                },
            },
        },
    )


def fixture_matchup() -> ToolResult:
    return tool_result(
        "matchup",
        data={
            "user_deck": list(HOG_CYCLE),
            "opponent_deck": [
                "Elixir Golem",
                "Battle Healer",
                "Night Witch",
                "Baby Dragon",
                "Dark Prince",
                "Rage",
                "Lightning",
                "Barbarian Barrel",
            ],
            "score": 42,
            "rating": "сложный",
            "reasons": ["Мало single-target DPS против Elixir Golem"],
            "advantages": ["Цикл быстрее"],
            "disadvantages": ["Слабо против танкового пуша"],
        },
    )


def fixture_battle_analysis() -> ToolResult:
    return tool_result(
        "battle_analysis",
        data={
            "battle_index": 0,
            "won": False,
            "opponent_name": "TestOpp",
            "matchup_score": 38,
            "outcome_summary": "Проиграл из-за ранней атаки",
            "reasons": ["Рано атаковал у моста", "Слил заклинание впустую"],
            "match_difficulty": {
                "difficulty": "hard",
                "rating": "сложный",
                "reasons": ["Невыгодный матчап"],
            },
            "match_plan": {
                "win_condition_window": "После плюса по эликсиру",
                "avoid": ["Не лезь первым у моста"],
                "phase_1": ["Играй от защиты"],
            },
        },
    )


def fixture_mechanics() -> ToolResult:
    return tool_result(
        "knowledge",
        data={
            "key": "tempo",
            "title": "Tempo",
            "summary": "Контроль ритма розыгрыша карт и давления",
            "example": "Хог + цикл после выгодного трейда",
            "tip": "Не стой с полным эликсиром",
            "answer": "Tempo — контроль темпа боя через выгодные розыгрыши",
        },
    )


def fixture_elixir_golem_counters() -> ToolResult:
    """ToolResult для «Чем лучше контрить Эликсирного голема?» — только реальные контры."""
    return tool_result(
        "game_coach",
        data={
            "topic": "vs_advice",
            "archetype": "Elixir Golem",
            "tips": [
                "Режь Elixir Golem Inferno Tower или Mini P.E.K.K.A",
                "Не лей заклинания в пустые сегменты",
            ],
            "user_deck": list(HOG_CYCLE),
            "opponent_deck": ["Elixir Golem"] + EGOLEM_COUNTERS[:7],
            "score": 55,
            "rating": "спорный",
            "reasons": ["Нужен single-target DPS"],
            "advantages": ["Inferno Tower танкует"],
            "disadvantages": [],
        },
    )


def fixture_failed_tool() -> ToolResult:
    return tool_result(
        "deck_analysis",
        ok=False,
        error_code="NEED_DECK_8",
        data={},
    )


def fixture_empty_facts() -> ToolResult:
    """ok=True, но без полезных facts/cards — empty envelope path."""
    return tool_result("deck_analysis", data={})


def ctx_from_tool_result(
    tr: ToolResult,
    *,
    message: str = "тест",
    intent: str = "analyze_deck",
) -> AIContext:
    ctx = AIContext(raw_message=message)
    ctx.intent.request = intent
    ctx.ok = bool(tr.ok)
    ctx.data = dict(tr.data or {})
    ctx.error_code = tr.error_code
    ctx.tool_outputs = {
        tr.tool: {
            "tool": tr.tool,
            "ok": bool(tr.ok),
            "data": dict(tr.data or {}),
            "error_code": tr.error_code,
            "call_id": tr.call_id or f"call_{tr.tool}",
        }
    }
    if tr.tool == "deck_builder" and isinstance(tr.data.get("deck_card"), dict):
        ctx.deck_card = dict(tr.data["deck_card"])
    return ctx


def envelope_from_tool(tr: ToolResult, **kwargs: Any) -> dict[str, Any]:
    ctx = ctx_from_tool_result(tr, **kwargs)
    if not tr.ok:
        return {
            "tool": tr.tool,
            "ok": False,
            "data": {
                "facts": [],
                "allowed_card_ids": [],
                "allowed_entities": [],
                "answer_constraints": [],
            },
        }
    return attach_render_facts(ctx)


FIXTURES: dict[str, Any] = {
    "CARD_INFO": fixture_card_info,
    "DECK_ANALYSIS": fixture_deck_analysis,
    "DECK_BUILDER": fixture_deck_builder,
    "RECOMMENDATION": fixture_recommendation,
    "MATCHUP": fixture_matchup,
    "BATTLE_ANALYSIS": fixture_battle_analysis,
    "MECHANICS": fixture_mechanics,
    "FAILED_TOOL": fixture_failed_tool,
    "EMPTY_FACTS": fixture_empty_facts,
    "ELIXIR_GOLEM_COUNTERS": fixture_elixir_golem_counters,
}
