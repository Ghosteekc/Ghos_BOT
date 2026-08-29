"""Build-deck follow-up: reuse core + alternative variants."""

from __future__ import annotations

from bot.services.ghosteek_ai.conversation.manager import ConversationManager
from bot.services.ghosteek_ai.conversation.state import ConversationState
from bot.services.ghosteek_ai.intents import (
    INTENT_BUILD_DECK,
    INTENT_CLARIFY,
    detect_intent,
    is_build_alternative_request,
    parse_build_variant_count,
)


def test_parse_build_variant_count():
    assert parse_build_variant_count("собери 2 колоды с хогом") == 2
    assert parse_build_variant_count("три варианта вокруг валькирии") == 3
    assert parse_build_variant_count("несколько колод с пеккой") == 2
    assert parse_build_variant_count("собери колоду с хогом") is None


def test_is_build_alternative_request():
    assert is_build_alternative_request("сделай еще один вариант с этой комбинацией")
    assert is_build_alternative_request("другую колоду с тем же ядром")
    assert not is_build_alternative_request("разбери мой бой")


def test_detect_alternative_as_build_deck():
    d = detect_intent("Сделай еще один вариант с этой комбинацией")
    assert d.intent == INTENT_BUILD_DECK
    assert d.prefer_alternative is True


def test_detect_multi_deck_with_core():
    d = detect_intent("Собери 2 колоды с валькирией и хогом")
    assert d.intent == INTENT_BUILD_DECK
    assert d.build_limit == 2
    assert "Valkyrie" in d.cards
    assert "Hog Rider" in d.cards


def test_followup_reuses_build_core():
    session = ConversationState()
    session.last_intent = INTENT_BUILD_DECK
    session.last_build_core = ["Valkyrie", "Hog Rider"]
    session.last_deck = [
        "Valkyrie",
        "Hog Rider",
        "Fire Spirit",
        "Skeletons",
        "Hunter",
        "Fireball",
        "The Log",
        "Firecracker",
    ]
    session.last_build_shown = [list(session.last_deck)]

    detected = detect_intent("Сделай еще один вариант с этой комбинацией")
    # без follow-up карт нет — enrichment подставляет ядро
    assert detected.cards == [] or detected.prefer_alternative
    ctx: dict = {}
    enriched = ConversationManager.apply_followup_enrichment(
        session, detected, "Сделай еще один вариант с этой комбинацией", ctx
    )
    assert enriched.intent == INTENT_BUILD_DECK
    assert enriched.cards == ["Valkyrie", "Hog Rider"]
    assert enriched.prefer_alternative is True
    assert ctx.get("exclude_decks")
    assert any("Valkyrie" in d and "Hunter" in d for d in ctx["exclude_decks"])


def test_update_persists_build_core():
    session = ConversationState()
    ConversationManager.update_from_ai_context(
        session,
        intent=INTENT_BUILD_DECK,
        service="Builder",
        ok=True,
        data={
            "core": ["Valkyrie", "Hog Rider"],
            "decks": [
                {
                    "cards": [
                        "Valkyrie",
                        "Hog Rider",
                        "Ice Spirit",
                        "Skeletons",
                        "Cannon",
                        "Fireball",
                        "The Log",
                        "Musketeer",
                    ]
                }
            ],
        },
    )
    assert session.last_build_core == ["Valkyrie", "Hog Rider"]
    assert len(session.last_deck) == 8
    assert len(session.last_build_shown) == 1
