"""Regression checks for the Cards Knowledge source of truth."""

from __future__ import annotations

from bot.services.card_knowledge import (
    canonical_card_names,
    evolution_has_role,
    load_card_catalog,
    resolve_canonical_card_name,
    validate_card_catalog,
)
from bot.services.card_knowledge_validation import validate_card_knowledge


def test_all_cards_load_with_unique_canonical_identities() -> None:
    cards = load_card_catalog()
    assert cards
    assert len(cards) == len(canonical_card_names())
    assert validate_card_catalog() == []


def test_canonical_name_normalization_never_guesses() -> None:
    assert resolve_canonical_card_name("  hOg RiDeR  ") == "Hog Rider"
    assert resolve_canonical_card_name("Invented Mega Unit") is None
    assert resolve_canonical_card_name("") is None


def test_airborne_cards_are_explicitly_tagged_in_catalog() -> None:
    cards = load_card_catalog()
    expected = {
        "Baby Dragon", "Balloon", "Bats", "Electro Dragon", "Flying Machine",
        "Inferno Dragon", "Lava Hound", "Mega Minion", "Minion Horde", "Minions",
        "Phoenix", "Skeleton Barrel", "Skeleton Dragons",
    }
    assert {name for name, data in cards.items() if "flying" in data["roles"]} == expected
    assert "flying" not in cards["Night Witch"]["roles"]
    assert "flying" not in cards["Royal Hogs"]["roles"]
    assert evolution_has_role("Royal Hogs", "flying")
    assert not evolution_has_role("Royal Hogs", "air_defense")


def test_profile_initialization_reads_canonical_catalog_before_legacy_metadata() -> None:
    from bot.services.card_profile import _profile_from_meta

    profile = _profile_from_meta("Dark Prince")
    assert {"anti_swarm", "counterpush", "splash"}.issubset(profile.roles)


def test_all_card_relationships_resolve_to_catalog_cards() -> None:
    assert validate_card_knowledge() == []


def test_rocket_is_a_strong_counter_to_elixir_collector() -> None:
    from bot.services.card_matchups import card_counters_target

    assert card_counters_target("Rocket", "Elixir Collector") == "strong"


def test_rocket_counter_targets_are_explicit_and_exclusive() -> None:
    from bot.services.card_knowledge import canonical_card_names
    from bot.services.card_matchups import card_counters_target

    assert {
        target
        for target in canonical_card_names()
        if card_counters_target("Rocket", target) == "strong"
    } == {"Sparky", "Witch", "Elixir Collector", "Elite Barbarians"}
    assert card_counters_target("Rocket", "Tesla") is None
