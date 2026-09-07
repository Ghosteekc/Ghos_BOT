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


def test_rocket_uses_deckshop_counter_data() -> None:
    from bot.services.card_matchups import card_counters_target

    assert card_counters_target("Rocket", "Hog Rider") == "strong"
    assert card_counters_target("Rocket", "Elixir Collector") == "strong"


def test_spells_have_no_incoming_counters() -> None:
    from bot.services.card_matchups import card_counters_target

    assert card_counters_target("Monk", "Fireball") is None
    assert card_counters_target("Rocket", "The Log") is None


def test_confirmed_counter_policy_overrides_deckshop_snapshot() -> None:
    from bot.services.card_matchups import card_counters_target, counters_in_deck

    assert card_counters_target("Hog Rider", "Valkyrie") is None
    assert card_counters_target("Mighty Miner", "Valkyrie") == "strong"
    assert card_counters_target("Tornado", "Goblin Barrel") == "strong"
    assert card_counters_target("Goblinstein", "Inferno Tower") == "strong"
    assert card_counters_target("Archers", "Bats") == "strong"
    assert card_counters_target("Archers", "Minions") == "strong"
    assert card_counters_target("Clone", "Executioner") is None
    assert card_counters_target("Mirror", "Executioner") is None

    strong, partial = counters_in_deck(
        "Valkyrie", ["Hog Rider", "Mighty Miner", "Valkyrie"]
    )
    assert strong == ["Mighty Miner", "Valkyrie"]
    assert partial == []

    strong, partial = counters_in_deck(
        "Goblin Barrel", ["Tornado", "Fireball", "The Log"]
    )
    assert "Tornado" in strong


def test_primary_win_conditions_are_not_generic_counter_sources() -> None:
    from bot.services.card_matchups import card_counters_target, get_matchups

    # Снимок знает эту связь, но слой Cards Knowledge не отдаёт её как контру.
    assert "Giant" in get_matchups("P.E.K.K.A").counters_strong
    assert card_counters_target("P.E.K.K.A", "Giant") is None
    for card in ("Mortar", "X-Bow", "Goblin Barrel"):
        assert card_counters_target(card, "Knight") is None

    # Вторичное давление сохраняет явно подтверждённую защитную роль.
    assert card_counters_target("Mighty Miner", "Valkyrie") == "strong"
    # Элитные варвары — явное исключение: это также сильный защитный бой.
    assert card_counters_target("Elite Barbarians", "Giant") == "strong"


def test_collection_counter_relations_only_expose_strong_known_cards() -> None:
    from bot.services.card_matchups import strong_counter_relations

    counters, countered_by = strong_counter_relations("Valkyrie")
    assert "Mighty Miner" in countered_by
    assert "Hog Rider" not in countered_by
    assert counters == sorted(counters)
    assert countered_by == sorted(countered_by)
    assert strong_counter_relations("Rocket")[1] == []
    assert strong_counter_relations("Clone") == ([], [])
    assert strong_counter_relations("Mirror") == ([], [])
    assert set(strong_counter_relations("Elixir Collector")[1]) == {
        "Earthquake", "Goblin Drill", "Lightning", "Miner", "Rocket", "Wall Breakers",
    }
    assert strong_counter_relations("Not A Card") == ([], [])


def test_cards_knowledge_records_composite_cards_and_champion_abilities() -> None:
    cards = load_card_catalog()
    assert {form["id"] for form in cards["Spirit Empress"]["forms"]} == {"ground", "air"}
    assert "flying" in next(form for form in cards["Spirit Empress"]["forms"] if form["id"] == "air")["roles"]
    assert {part["id"] for part in cards["Goblinstein"]["components"]} == {"monster", "doctor"}
    assert cards["Goblinstein"]["abilities"] == ["Lightning Link"]
    assert cards["Archer Queen"]["abilities"] == ["Cloaking Cape"]
