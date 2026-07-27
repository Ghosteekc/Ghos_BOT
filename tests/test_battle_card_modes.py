"""Tests for battlelog evolution / hero mode parsing."""
from __future__ import annotations

from bot.services.card_icons import battle_card_modes, cards_from_team, parse_battle_card


def test_hero_only_dark_prince_and_giant():
    team = {
        "cards": [
            {
                "name": "Archers",
                "evolutionLevel": 1,
                "maxEvolutionLevel": 1,
                "iconUrls": {
                    "medium": "m",
                    "evolutionMedium": "e",
                },
                "elixirCost": 3,
                "level": 11,
                "maxLevel": 16,
                "rarity": "common",
            },
            {
                "name": "Dark Prince",
                "evolutionLevel": 2,
                "maxEvolutionLevel": 2,
                "iconUrls": {"medium": "m", "heroMedium": "h"},
                "elixirCost": 4,
                "level": 6,
                "maxLevel": 11,
                "rarity": "epic",
            },
            {
                "name": "Giant",
                "evolutionLevel": 2,
                "maxEvolutionLevel": 2,
                "iconUrls": {"medium": "m", "heroMedium": "h"},
                "elixirCost": 5,
                "level": 9,
                "maxLevel": 14,
                "rarity": "rare",
            },
            {
                "name": "Prince",
                "iconUrls": {"medium": "m"},
                "elixirCost": 5,
                "level": 6,
                "maxLevel": 11,
                "rarity": "epic",
            },
        ]
    }
    parsed = cards_from_team(team)
    by_name = {c["name"]: c for c in parsed}
    assert by_name["Archers"]["evolution_level"] == 1
    assert by_name["Archers"]["is_hero"] is False
    assert by_name["Dark Prince"]["is_hero"] is True
    assert by_name["Dark Prince"]["evolution_level"] == 0
    assert by_name["Giant"]["is_hero"] is True
    assert by_name["Giant"]["evolution_level"] == 0
    assert by_name["Prince"]["is_hero"] is False


def test_hero_only_base_has_no_evolution_level():
    card = {
        "name": "Giant",
        "maxEvolutionLevel": 2,
        "iconUrls": {"medium": "m", "heroMedium": "h"},
        "elixirCost": 5,
        "level": 9,
        "maxLevel": 14,
        "rarity": "rare",
    }
    evo, is_hero = battle_card_modes(card)
    assert evo == 0
    assert is_hero is False
    parsed = parse_battle_card(card)
    assert parsed["is_hero"] is False
    assert parsed["evolution_level"] == 0


def test_dual_path_knight():
    evo_card = {
        "name": "Knight",
        "evolutionLevel": 1,
        "maxEvolutionLevel": 3,
        "iconUrls": {"medium": "m", "heroMedium": "h", "evolutionMedium": "e"},
    }
    hero_card = {**evo_card, "evolutionLevel": 2}
    assert battle_card_modes(evo_card) == (1, False)
    assert battle_card_modes(hero_card) == (0, True)


def test_two_evo_plus_two_champions_demotes_extra_evo():
    """March 2026: max 3 specials — 2 evo + 2 champions is illegal."""
    from bot.services.card_icons import normalize_deck_upgrades

    cards = [
        {"name": "P.E.K.K.A", "evolution_level": 1, "is_hero": False, "rarity": "epic", "cost": 7, "icon": ""},
        {"name": "Monk", "evolution_level": 0, "is_hero": False, "rarity": "champion", "cost": 5, "icon": ""},
        {"name": "Ram Rider", "evolution_level": 1, "is_hero": False, "rarity": "legendary", "cost": 5, "icon": ""},
        {"name": "Little Prince", "evolution_level": 0, "is_hero": False, "rarity": "champion", "cost": 3, "icon": ""},
        {"name": "Firecracker", "evolution_level": 0, "is_hero": False, "rarity": "common", "cost": 3, "icon": ""},
        {"name": "Arrows", "evolution_level": 0, "is_hero": False, "rarity": "common", "cost": 3, "icon": ""},
        {"name": "Goblin Curse", "evolution_level": 0, "is_hero": False, "rarity": "rare", "cost": 2, "icon": ""},
        {"name": "Skeleton Army", "evolution_level": 0, "is_hero": False, "rarity": "epic", "cost": 3, "icon": ""},
    ]
    result = normalize_deck_upgrades(cards)
    evo_count = sum(1 for c in result if int(c.get("evolution_level") or 0) >= 1)
    champ_count = sum(1 for c in result if (c.get("rarity") or "").lower() == "champion")
    assert champ_count == 2
    assert evo_count == 1
    assert evo_count + champ_count <= 3
    # Keep first evo (P.E.K.K.A), demote trailing Ram Rider
    by_name = {c["name"]: c for c in result}
    assert by_name["P.E.K.K.A"]["evolution_level"] == 1
    assert by_name["Ram Rider"]["evolution_level"] == 0


def test_two_evo_plus_one_hero_allowed():
    from bot.services.card_icons import normalize_deck_upgrades

    cards = [
        {"name": "Archers", "evolution_level": 1, "is_hero": False, "rarity": "common", "cost": 3, "icon": ""},
        {"name": "Giant", "evolution_level": 0, "is_hero": True, "rarity": "rare", "cost": 5, "icon": ""},
        {"name": "Skeletons", "evolution_level": 1, "is_hero": False, "rarity": "common", "cost": 1, "icon": ""},
        {"name": "Fireball", "evolution_level": 0, "is_hero": False, "rarity": "rare", "cost": 4, "icon": ""},
    ]
    result = normalize_deck_upgrades(cards)
    evo_count = sum(1 for c in result if int(c.get("evolution_level") or 0) >= 1)
    hero_count = sum(1 for c in result if c.get("is_hero"))
    assert evo_count == 2
    assert hero_count == 1
