"""Regression: real counters must beat fragile swarm answers in matchup UI."""
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


def test_valkyrie_strongly_counters_golden_knight():
    assert card_counters_target("Valkyrie", "Golden Knight") == "strong"


def test_bats_do_not_count_as_golden_knight_answer():
    assert card_counters_target("Bats", "Golden Knight") is None


def test_minions_do_not_count_as_golden_knight_answer():
    assert card_counters_target("Minions", "Golden Knight") is None


def test_user_deck_has_strong_answer_to_golden_knight():
    strong, partial = counters_in_deck("Golden Knight", USER_DECK)
    assert "Valkyrie" in strong
    assert "Bats" not in strong
    assert "Bats" not in partial


def test_golden_knight_not_flagged_dangerous_when_valkyrie_present():
    report = analyze_tactical_matchup(USER_DECK, OPP_DECK)
    dangerous = {d.name for d in report.danger_cards}
    assert "Golden Knight" not in dangerous


def test_classic_golden_knight_answers_are_strong():
    for card in ("Mini P.E.K.K.A", "Guards", "Knight", "Bomb Tower", "Skeleton Army"):
        assert card_counters_target(card, "Golden Knight") == "strong", card


def test_bats_denied_vs_splash_tanks():
    for threat in ("Mega Knight", "Boss Bandit", "Wizard", "Executioner"):
        assert card_counters_target("Bats", threat) is None, threat
