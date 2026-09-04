"""DeckShop snapshot tiers are used without legacy counter overrides."""
from __future__ import annotations

from bot.services.card_matchups import card_counters_target, counters_in_deck
from bot.services.tactical_matchup import analyze_tactical_matchup


USER_DECK = [
    "Bats",
    "Little Prince",
    "Valkyrie",
    "Wall Breakers",
    "Giant Snowball",
    "Bomb Tower",
    "Tornado",
    "Miner",
]
OPP_DECK = [
    "Skeleton Barrel",
    "Wizard",
    "Golden Knight",
    "Fireball",
    "Royal Delivery",
    "Mirror",
    "Arrows",
    "Mini P.E.K.K.A",
]


def test_valkyrie_is_a_partial_deckshop_answer_to_golden_knight():
    assert card_counters_target("Valkyrie", "Golden Knight") == "partial"


def test_bats_keep_their_deckshop_partial_answer_to_golden_knight():
    assert card_counters_target("Bats", "Golden Knight") == "partial"


def test_minions_keep_their_deckshop_partial_answer_to_golden_knight():
    assert card_counters_target("Minions", "Golden Knight") == "partial"


def test_user_deck_has_partial_deckshop_answers_to_golden_knight():
    strong, partial = counters_in_deck("Golden Knight", USER_DECK)
    assert strong == []
    assert {"Valkyrie", "Bats"}.issubset(partial)


def test_golden_knight_is_flagged_dangerous_without_a_strong_deckshop_answer():
    report = analyze_tactical_matchup(USER_DECK, OPP_DECK)
    dangerous = {d.name for d in report.danger_cards}
    assert "Golden Knight" in dangerous


def test_golden_knight_answers_match_deckshop_tiers():
    expected = {
        "Mini P.E.K.K.A": "partial",
        "Guards": "partial",
        "Knight": "partial",
        "Bomb Tower": "partial",
        "Skeleton Army": None,
    }
    for card, tier in expected.items():
        assert card_counters_target(card, "Golden Knight") == tier, card


def test_bats_match_deckshop_tiers_against_splash_threats():
    expected = {
        "Mega Knight": None,
        "Boss Bandit": "partial",
        "Wizard": None,
        "Executioner": None,
    }
    for threat, tier in expected.items():
        assert card_counters_target("Bats", threat) == tier, threat
