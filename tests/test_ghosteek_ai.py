"""Тесты Ghosteek AI: intent routing и честные fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.models.database import User
from bot.services.ghosteek_ai.composer import compose_answer
from bot.services.ghosteek_ai.intents import (
    INTENT_ANALYZE_DECK,
    INTENT_BUILD_DECK,
    INTENT_CARD_INFO,
    INTENT_CLARIFY,
    INTENT_EXPLAIN_MECHANIC,
    INTENT_GAME_COACH,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    INTENT_MATCHUP,
    INTENT_UNSUPPORTED,
    SERVICE_BY_INTENT,
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
        ("Собери колоду", INTENT_BUILD_DECK),
        ("Построй колоду", INTENT_BUILD_DECK),
        ("Хочу играть через Хога", INTENT_BUILD_DECK),
        ("Разбери мою колоду", INTENT_ANALYZE_DECK),
        ("что заменить в колоде", INTENT_IMPROVE_DECK),
        ("улучши колоду", INTENT_IMPROVE_DECK),
        ("разобрать матчап", INTENT_MATCHUP),
        ("матчап vs", INTENT_MATCHUP),
        ("последний бой", INTENT_LAST_BATTLE),
        ("разбери мой бой", INTENT_LAST_BATTLE),
        ("почему проиграл", INTENT_LAST_BATTLE),
        ("что делает Палач", INTENT_CARD_INFO),
        ("что такое cycle", INTENT_EXPLAIN_MECHANIC),
        ("что такое positive elixir trade", INTENT_EXPLAIN_MECHANIC),
        ("что такое bridge spam", INTENT_EXPLAIN_MECHANIC),
        ("что такое dual lane pressure", INTENT_EXPLAIN_MECHANIC),
        ("Как апнуть кубки?", INTENT_GAME_COACH),
        ("Как играть против Lavaloon?", INTENT_GAME_COACH),
        ("сколько эликсира в руке", INTENT_UNSUPPORTED),
        ("урон по карте в бою", INTENT_UNSUPPORTED),
        ("абракадабра xyz", INTENT_CLARIFY),
        ("мой винрейт", INTENT_CLARIFY),
        ("что в мете", INTENT_CLARIFY),
    ],
)
def test_intent_routing_fixed_phrases(phrase: str, intent: str):
    detected = detect_intent(phrase)
    assert detected.intent == intent
    assert detected.service == SERVICE_BY_INTENT[intent]


def test_does_not_guess_from_cards_alone():
    """Без явного глагола — clarify, не Analyzer/Card DB."""
    assert detect_intent("", context_cards=HOG_CYCLE).intent == INTENT_CLARIFY
    assert detect_intent("Hog Rider Ice Golem Musketeer").intent == INTENT_CLARIFY
    assert detect_intent("Палач").intent == INTENT_CLARIFY


def test_build_through_hog_extracts_card():
    d = detect_intent("Хочу играть через Хога")
    assert d.intent == INTENT_BUILD_DECK
    assert "Hog Rider" in d.cards


def test_mechanic_query_set():
    d = detect_intent("что такое cycle")
    assert d.mechanic_query == "cycle"


def test_unsupported_honest_refusal_no_fake_numbers():
    detected = detect_intent("сколько урона наносит Хог по башне")
    assert detected.intent == INTENT_UNSUPPORTED


@pytest.mark.asyncio
async def test_unsupported_answer_mentions_cr_api():
    result = await ask_ghosteek_ai("сколько эликсира в руке было", _user())
    assert result.intent == INTENT_UNSUPPORTED
    low = result.answer.lower()
    assert "clash royale" in low or "не предоставляет" in low
    assert "3." not in result.answer


@pytest.mark.asyncio
async def test_clarify_asks_not_guesses():
    result = await ask_ghosteek_ai("привет", _user())
    assert result.intent == INTENT_CLARIFY
    assert "Уточните" in result.answer
    assert "Builder" in result.answer


@pytest.mark.asyncio
async def test_explain_mechanic_from_knowledge_base():
    result = await ask_ghosteek_ai("что такое cycle", _user())
    assert result.intent == INTENT_EXPLAIN_MECHANIC
    assert result.sources.get("service") == "Knowledge Base"
    assert "цикл" in result.answer.lower() or "Cycle" in result.answer


@pytest.mark.asyncio
async def test_game_coach_climb():
    result = await ask_ghosteek_ai("Как апнуть кубки?", _user())
    assert result.intent == INTENT_GAME_COACH
    assert "куб" in result.answer.lower() or "колод" in result.answer.lower()


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
    assert result.sources.get("service") == "Analyzer"
    assert "цикл" in result.answer.lower() or "Хог" in result.answer or "давлени" in result.answer
    assert "72" in result.answer or "синергия" in result.answer.lower()
    mock_analyze.assert_called_once()


@pytest.mark.asyncio
async def test_build_through_hog_uses_meta_templates():
    result = await ask_ghosteek_ai("Хочу играть через Хога", _user())
    assert result.intent == INTENT_BUILD_DECK
    assert result.sources.get("service") == "Builder"
    assert result.sources.get("ok") is True
    assert "Hog Rider" in str(result.sources.get("data"))


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
