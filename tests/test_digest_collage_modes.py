"""Digest collage card selection keeps evo/hero from mine slots / restored cache."""
from __future__ import annotations

from bot.services.weekly_digest import collage_cards_for_deck, _deck_upgrade_score


def _card(name: str, *, evo: int = 0, hero: bool = False) -> dict:
    return {
        "name": name,
        "evolution_level": evo,
        "is_hero": hero,
        "cost": 4,
        "icon": "",
        "rarity": "rare",
        "slot": 0,
    }


def _deck(*cards: dict) -> list[dict]:
    return [{**c, "slot": i} for i, c in enumerate(cards)]


NAMES = [
    "Tesla",
    "Valkyrie",
    "Bowler",
    "Goblin Cage",
    "Poison",
    "Barbarian Barrel",
    "Furnace",
    "Electro Spirit",
]


def test_collage_uses_restored_cache_modes():
    """user_deck_json restore uses evolution_level/is_hero — must not be skipped."""
    rich = _deck(
        _card("Tesla", evo=1),
        _card("Valkyrie", hero=True),
        _card("Bowler", hero=True),
        *[_card(n) for n in NAMES[3:]],
    )
    battle = {
        "type": "PvP",
        "battleTime": "20260810T120000.000Z",
        "team": [{"tag": "#AAA", "cards": rich, "crowns": 1}],
        "opponent": [{"crowns": 0}],
    }
    deck = {"cards": NAMES, "deck_cards": []}
    out = collage_cards_for_deck([battle], "#AAA", deck)
    by_name = {c["name"]: c for c in out}
    assert by_name["Tesla"]["evolution_level"] == 1
    assert by_name["Valkyrie"]["is_hero"] is True
    assert by_name["Bowler"]["is_hero"] is True
    assert _deck_upgrade_score(out) > 0


def test_collage_merges_tracked_mine_slot():
    stubs = _deck(*[_card(n) for n in NAMES])
    tracked = _deck(
        _card("Tesla", evo=1),
        _card("Valkyrie", hero=True),
        _card("Bowler", hero=True),
        *[_card(n) for n in NAMES[3:]],
    )
    deck = {"cards": NAMES, "deck_cards": stubs}
    out = collage_cards_for_deck([], "#AAA", deck, extra_variants=[tracked])
    by_name = {c["name"]: c for c in out}
    assert by_name["Tesla"]["evolution_level"] == 1
    assert by_name["Valkyrie"]["is_hero"] is True
    assert by_name["Bowler"]["is_hero"] is True


def test_collage_does_not_clamp_away_display_modes():
    tracked = _deck(
        _card("Tesla", evo=1),
        _card("Valkyrie", hero=True),
        _card("Bowler", hero=True),
        *[_card(n) for n in NAMES[3:]],
    )
    deck = {"cards": NAMES, "deck_cards": tracked}
    out = collage_cards_for_deck([], "#AAA", deck)
    by_name = {c["name"]: c for c in out}
    assert by_name["Tesla"]["evolution_level"] == 1
    assert by_name["Valkyrie"]["is_hero"] is True
    assert by_name["Bowler"]["is_hero"] is True
