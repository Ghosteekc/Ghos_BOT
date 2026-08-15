"""NL build_deck: разговорные формулировки + русские падежи карт."""
from __future__ import annotations

import pytest

from bot.services.ghosteek_ai.intents import (
    INTENT_BUILD_DECK,
    INTENT_CARD_INFO,
    INTENT_CLARIFY,
    INTENT_GAME_COACH,
    INTENT_LAST_BATTLE,
    detect_intent,
    extract_cards_from_text,
)


@pytest.mark.parametrize(
    "phrase",
    [
        "Собери колоду с Ведьма",
        "Собери колоду с ведьмой",
        "Сделай колоду с ведьмой",
        "Создай колоду с ведьмой",
        "Хочу колоду с ведьмой",
        "Хочу деку с ведьмой",
        "Подбери колоду с ведьмой",
        "Составь деку вокруг ведьмы",
        "Давай колоду через ведьму",
        "Можешь сделать мне колоду с ведьмой?",
        "Помоги собрать деку с ведьмой",
        "Сделай нормальную деку с ведьмой",
        "сделай колоду с ведьмой пожалуйста",
        "Создай колоду с хогом",
        "Сделай колоду с хогом",
    ],
)
def test_nl_build_deck_witch_hog(phrase: str):
    d = detect_intent(phrase)
    assert d.intent == INTENT_BUILD_DECK, phrase
    if "хог" in phrase.lower():
        assert "Hog Rider" in d.cards, phrase
    else:
        assert "Witch" in d.cards, phrase


def test_extract_witch_cases():
    for form in ("ведьма", "ведьмой", "ведьму", "ведьмы", "ведьме"):
        assert extract_cards_from_text(f"с {form}") == ["Witch"], form


def test_elixir_golem_not_plain_golem():
    for phrase in (
        "Сделай колоду с эликсирным големом",
        "Собери колоду с эликсирным големом",
        "Хочу деку через эликсирного голема",
        "эликсирный голем",
    ):
        cards = extract_cards_from_text(phrase)
        assert "Elixir Golem" in cards, phrase
        assert "Golem" not in cards, phrase
    d = detect_intent("Сделай колоду с эликсирным големом")
    assert d.intent == INTENT_BUILD_DECK
    assert d.cards == ["Elixir Golem"]


def test_skeleton_king_spoken_orders():
    for phrase in (
        "Сделай колоду с Королём Скелетов",
        "Собери колоду с королем скелетов",
        "Хочу деку через короля скелетов",
        "Король Скелетов",
        "скелет-король",
        "с скелет-королём",
    ):
        cards = extract_cards_from_text(phrase)
        assert "Skeleton King" in cards, (phrase, cards)
    d = detect_intent("Сделай колоду с Королём Скелетов")
    assert d.intent == INTENT_BUILD_DECK
    assert d.cards == ["Skeleton King"]


def test_skeleton_barrel_not_barbarian_barrel():
    for phrase in (
        "Давай ка сделаем колоду со скелетной бочкой",
        "Собери колоду со скелетной бочкой",
        "Сделай колоду со скелетной бочкой",
        "Хочу деку со скелетной бочкой",
        "колода со скелетной бочкой",
        "скелетная бочка",
        "со скелетной бочкой",
        "Skeleton Barrel",
    ):
        cards = extract_cards_from_text(phrase)
        assert "Skeleton Barrel" in cards, (phrase, cards)
        assert "Barbarian Barrel" not in cards, (phrase, cards)
        assert "Goblin Barrel" not in cards, (phrase, cards)
    d = detect_intent("Давай ка сделаем колоду со скелетной бочкой")
    assert d.intent == INTENT_BUILD_DECK
    assert d.cards == ["Skeleton Barrel"]


def test_slang_aliases_plevaka_babulia():
    assert extract_cards_from_text("Плевака") == ["Dart Goblin"]
    assert extract_cards_from_text("с плевакой") == ["Dart Goblin"]
    assert extract_cards_from_text("Бабуля") == ["Mother Witch"]
    assert extract_cards_from_text("через бабулю") == ["Mother Witch"]
    assert "Mega Knight" in extract_cards_from_text("меганайт")
    assert "Elite Barbarians" in extract_cards_from_text("элитки")
    assert "Ice Golem" in extract_cards_from_text("терпила")


def test_build_followup_card_only():
    from bot.services.ghosteek_ai.conversation.manager import ConversationManager
    from bot.services.ghosteek_ai.conversation.state import ConversationState

    session = ConversationState()
    session.last_intent = INTENT_BUILD_DECK
    detected = detect_intent("Король Скелетов")
    assert detected.intent == INTENT_CLARIFY
    assert detected.cards == ["Skeleton King"]
    enriched = ConversationManager.apply_followup_enrichment(
        session, detected, "Король Скелетов", {}
    )
    assert enriched.intent == INTENT_BUILD_DECK
    assert enriched.cards == ["Skeleton King"]


def test_negative_not_build_deck():
    assert detect_intent("Что делает ведьма?").intent == INTENT_CARD_INFO
    assert detect_intent("Что делает ведьма?").cards == ["Witch"]

    d = detect_intent("Чем контрить ведьму?")
    assert d.intent == INTENT_GAME_COACH
    assert "Witch" in d.cards

    assert detect_intent("Ведьма + Хог + Огненный шар").intent == INTENT_CLARIFY
    assert detect_intent("Разбери мой последний бой").intent == INTENT_LAST_BATTLE
