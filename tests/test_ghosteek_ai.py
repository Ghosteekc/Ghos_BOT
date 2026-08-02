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
from bot.services.ghosteek_ai.voice import coach_reply


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
    assert "нет" in low or "выдум" in low or "данных" in low
    assert "api" not in low
    assert "как ии" not in low
    assert "3." not in result.answer
    assert result.sources.get("constraints")


@pytest.mark.parametrize(
    "phrase",
    [
        "сколько урона нанёс Хог в том бою",
        "посмотри реплей и скажи",
        "сколько раз была сыграна карта в бою",
        "какая карта была в руке на 30 секунде",
        "точный хп башни после удара",
    ],
)
def test_constraint_unsupported_requests(phrase: str):
    assert detect_intent(phrase).intent == INTENT_UNSUPPORTED


def test_sanitize_blocks_forbidden_replay_claims():
    from bot.services.ghosteek_ai.constraints import contains_forbidden_claim, sanitize_answer

    bad = "Я видел реплей: карта нанесла 1240 урона и сыграла 5 раз."
    assert contains_forbidden_claim(bad)
    cleaned = sanitize_answer(bad)
    assert "видел реплей" not in cleaned.lower()
    assert "выдум" in cleaned.lower() or "нет" in cleaned.lower()
    assert "api" not in cleaned.lower()


def test_strip_internal_jargon_from_answers():
    from bot.services.ghosteek_ai.constraints import strip_internal_jargon

    raw = "Clash Royale API не отдаёт урон. Смотри Matchup Analyzer."
    cleaned = strip_internal_jargon(raw).lower()
    assert "api" not in cleaned
    assert "matchup analyzer" not in cleaned
    assert "данн" in cleaned or "разбор" in cleaned


@pytest.mark.asyncio
async def test_clarify_asks_not_guesses():
    result = await ask_ghosteek_ai("привет", _user())
    assert result.intent == INTENT_CLARIFY
    assert "уточн" in result.answer.lower()
    assert "как ии" not in result.answer.lower()


@pytest.mark.parametrize(
    "phrase,key_substr",
    [
        ("что такое Cycle", "цикл"),
        ("что такое Beatdown", "танк"),
        ("что такое Bridge Spam", "мост"),
        ("что такое Split Push", "лини"),
        ("что такое Positive Elixir Trade", "меньше"),
        ("что такое Tempo", "ритм"),
        ("что такое Counterpush", "защит"),
        ("что такое Win Condition", "башн"),
        ("что такое Mini Tank", "танк"),
        ("что такое Reset", "сброс"),
        ("что такое Overcommit", "много"),
        ("что такое Spell Cycle", "спелл"),
        ("что такое Lane Control", "лини"),
        ("что такое Pressure", "давлен"),
        ("что такое Support Card", "поддерж"),
        ("что такое Kiting", "оттяг"),
    ],
)
@pytest.mark.asyncio
async def test_knowledge_base_terms_are_short_with_examples(phrase: str, key_substr: str):
    result = await ask_ghosteek_ai(phrase, _user())
    assert result.intent == INTENT_EXPLAIN_MECHANIC
    assert result.sources.get("ok") is True
    low = result.answer.lower()
    assert key_substr in low or "пример" in low
    assert "пример" in low
    # без воды: не больше ~8 предложений
    sentences = [s for s in result.answer.replace("\n", " ").split(".") if s.strip()]
    assert len(sentences) <= 8


@pytest.mark.asyncio
async def test_unknown_mechanic_is_honest():
    result = await ask_ghosteek_ai("что такое quantum elixir singularity", _user())
    assert result.intent == INTENT_EXPLAIN_MECHANIC
    assert result.sources.get("ok") is False
    low = result.answer.lower()
    assert "нет" in low or "пока" in low
    assert "выдум" in low or "cycle" in low or "tempo" in low


@pytest.mark.asyncio
async def test_game_coach_climb():
    result = await ask_ghosteek_ai("Как апнуть кубки?", _user())
    assert result.intent == INTENT_GAME_COACH
    assert "куб" in result.answer.lower() or "колод" in result.answer.lower()
    assert "как ии" not in result.answer.lower()


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
    assert "recommendationengine" not in result.answer.lower()
    assert "как ии" not in result.answer.lower()
    mock_analyze.assert_called_once()


@pytest.mark.asyncio
async def test_coach_voice_structure_on_matchup():
    answer = compose_answer(
        {
            "intent": INTENT_MATCHUP,
            "ok": True,
            "data": {
                "rating": "Сложный",
                "score": 72,
                "reasons": ["У соперника сильная защита зданиями.", "Твой Hog упирается в Tesla."],
                "advantages": ["Дави, когда Tesla уже сыграна."],
                "disadvantages": [],
            },
        }
    )
    parts = [p for p in answer.split("\n\n") if p.strip()]
    assert len(parts) >= 3
    assert "как ии" not in answer.lower()
    assert "хорошие показатели" not in answer.lower()


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
            "error": coach_reply(
                "Истории боёв пока нет.",
                why="Без боя разбирать нечего.",
                action="Синхронизируй бои.",
            ),
            "data": {},
        }
    )
    assert "истор" in answer.lower()
    assert "победа" not in answer.lower()


@pytest.mark.asyncio
async def test_session_remembers_deck_for_improve_followup():
    from bot.services.ghosteek_ai.session_context import clear_session, get_session

    user = _user()
    clear_session(user.telegram_id)

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
            return_value=(70, ["связка Хог"]),
        ),
    ):
        public = {
            "coaching": {"play_style": "цикл", "strengths": ["темп"], "usage_tips": ["дави"]},
            "game_plan": {"how_to_win": "Хог", "critical_weaknesses": []},
            "improvement_plan": {
                "needed": True,
                "steps": [{"message": "Замени Skeletons на Ice Spirit для стабильности."}],
            },
            "balance_issues": {"messages": []},
        }
        rec = MagicMock()
        rec.to_public_dict.return_value = public
        mock_analyze.return_value = rec

        first = await ask_ghosteek_ai("разбери мою колоду", user, context={"cards": HOG_CYCLE})
        assert first.intent == INTENT_ANALYZE_DECK
        session = get_session(user.telegram_id)
        assert session is not None
        assert session.last_deck == HOG_CYCLE

        second = await ask_ghosteek_ai("А что заменить?", user)
        assert second.intent == INTENT_IMPROVE_DECK
        assert second.sources.get("ok") is True
        # Второй вызов с apply_swaps=True и той же колодой из сессии
        assert mock_analyze.call_count == 2
        args, kwargs = mock_analyze.call_args
        assert list(args[0]) == HOG_CYCLE
        assert kwargs.get("apply_swaps") is True

    clear_session(user.telegram_id)


@pytest.mark.asyncio
async def test_session_clears_on_ttl_and_explicit_clear():
    from bot.services.ghosteek_ai import session_context as sc

    user = _user()
    sc.clear_session(user.telegram_id)
    session = sc.get_or_create_session(user.telegram_id)
    session.last_deck = list(HOG_CYCLE)
    session.updated_at = 0  # протухла
    assert sc.get_session(user.telegram_id) is None

    session = sc.get_or_create_session(user.telegram_id)
    session.last_deck = list(HOG_CYCLE)
    sc.clear_session(user.telegram_id)
    assert sc.get_session(user.telegram_id) is None
