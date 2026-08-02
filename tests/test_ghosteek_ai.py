"""Тесты Ghosteek AI: intent routing и честные fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.models.database import User
from bot.services.ghosteek_ai.composer import compose_answer
from bot.services.ghosteek_ai.intents import (
    INTENT_ANALYZE_DECK,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    INTENT_META,
    INTENT_STATS,
    INTENT_UNSUPPORTED,
    INTENT_UNKNOWN,
    detect_intent,
)
from bot.services.ghosteek_ai.service import ask_ghosteek_ai


HOG_CYCLE = [
    "Hog Rider",
    "Ice Golem",
    "Musketeer",
    "Cannon",
    "Ice Spirit",
    "Skeletons",
    "The Log",
    "Fireball",
]


def _user() -> User:
    u = User(telegram_id=1, player_tag="#TESTTAG", player_name="Tester")
    u.arena_id = 20
    u.trophies = 7000
    return u


@pytest.mark.parametrize(
    "phrase,intent",
    [
        ("Разбери мою колоду", INTENT_ANALYZE_DECK),
        ("что заменить в колоде", INTENT_IMPROVE_DECK),
        ("улучши колоду", INTENT_IMPROVE_DECK),
        ("последний бой", INTENT_LAST_BATTLE),
        ("почему проиграл", INTENT_LAST_BATTLE),
        ("мой винрейт", INTENT_STATS),
        ("что в мете", INTENT_META),
        ("сколько эликсира в руке", INTENT_UNSUPPORTED),
        ("урон по карте в бою", INTENT_UNSUPPORTED),
        ("абракадабра xyz", INTENT_UNKNOWN),
    ],
)
def test_intent_routing_fixed_phrases(phrase: str, intent: str):
    assert detect_intent(phrase).intent == intent


def test_unsupported_honest_refusal_no_fake_numbers():
    detected = detect_intent("сколько урона наносит Хог по башне")
    assert detected.intent == INTENT_UNSUPPORTED


@pytest.mark.asyncio
async def test_unsupported_answer_mentions_cr_api():
    result = await ask_ghosteek_ai("сколько эликсира в руке было", _user())
    assert result.intent == INTENT_UNSUPPORTED
    low = result.answer.lower()
    assert "clash royale" in low or "не предоставляет" in low
    # Не должно быть выдуманных боевых цифр вроде «3.2 эликсира»
    assert "3." not in result.answer


@pytest.mark.asyncio
async def test_analyze_deck_uses_recommendation_engine():
    with (
        patch(
            "bot.services.ghosteek_ai.router._resolve_player_deck",
            new_callable=AsyncMock,
            return_value=HOG_CYCLE,
        ),
        patch(
            "bot.services.ghosteek_ai.router.RecommendationEngine.analyze",
        ) as mock_analyze,
        patch(
            "bot.services.ghosteek_ai.router.calculate_deck_synergy",
            return_value=(72, ["Хог + Мушкетёр: давление"]),
        ),
    ):
        public = {
            "coaching": {
                "play_style": "цикл",
                "strengths": ["быстрый цикл"],
                "usage_tips": ["давите правой"],
            },
            "game_plan": {"how_to_win": "давление Хогом", "critical_weaknesses": []},
            "improvement_plan": {"needed": False, "steps": []},
            "balance_issues": {"messages": []},
        }
        rec = MagicMock()
        rec.to_public_dict.return_value = public
        mock_analyze.return_value = rec

        result = await ask_ghosteek_ai("разбери мою колоду", _user(), context={"cards": HOG_CYCLE})

    assert result.intent == INTENT_ANALYZE_DECK
    assert "цикл" in result.answer.lower() or "Хог" in result.answer or "давлени" in result.answer
    assert "72" in result.answer or "синергия" in result.answer.lower()
    mock_analyze.assert_called_once()


@pytest.mark.asyncio
async def test_last_battle_without_history_is_honest():
    with patch(
        "bot.services.ghosteek_ai.router.load_and_persist",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await ask_ghosteek_ai("последний бой", _user())

    assert result.intent == INTENT_LAST_BATTLE
    low = result.answer.lower()
    assert "нет" in low or "истор" in low
    assert "победа" not in low
    assert "/100" not in result.answer


def test_compose_does_not_invent_when_ok_false():
    answer = compose_answer(
        {
            "intent": INTENT_LAST_BATTLE,
            "ok": False,
            "error": "Нет истории боёв. Синхронизируйте бои или сыграйте ladder/PvP.",
            "data": {},
        }
    )
    assert "Нет истории" in answer
    assert "матчап" not in answer.lower()
