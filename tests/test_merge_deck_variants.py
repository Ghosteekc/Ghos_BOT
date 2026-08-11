"""OR-merge of evolution/hero across cache stubs and alternate orders."""
from __future__ import annotations

from bot.services.card_icons import (
    deck_upgrade_score,
    merge_deck_variants,
    or_merge_modes_onto,
    parse_deck_cards_json,
    serialize_deck_cards,
)


def _card(name: str, *, evo: int = 0, hero: bool = False, rarity: str = "common") -> dict:
    return {
        "name": name,
        "evolution_level": evo,
        "is_hero": hero,
        "rarity": rarity,
        "cost": 3,
        "icon": "",
        "slot": 0,
    }


def _deck(*cards: dict) -> list[dict]:
    out = []
    for i, c in enumerate(cards):
        item = dict(c)
        item["slot"] = i
        out.append(item)
    return out


NAMES = [
    "Valkyrie",
    "Hog Rider",
    "Executioner",
    "Tornado",
    "The Log",
    "Fireball",
    "Guards",
    "Mighty Miner",
]


def test_merge_keeps_evo_despite_cache_stubs_majority():
    rich = _deck(
        _card("Valkyrie", evo=1, rarity="rare"),
        _card("Hog Rider", evo=1, rarity="rare"),
        *[_card(n, rarity="champion" if n == "Mighty Miner" else "epic") for n in NAMES[2:]],
    )
    stubs = [
        _deck(*[_card(n) for n in NAMES])
        for _ in range(20)
    ]
    merged = merge_deck_variants([rich, *stubs])
    by_name = {c["name"]: c for c in merged}
    assert by_name["Valkyrie"]["evolution_level"] == 1
    assert by_name["Hog Rider"]["evolution_level"] == 1


def test_merge_or_across_different_slot_orders():
    order_a = _deck(*[_card(n) for n in NAMES])
    order_b_names = list(reversed(NAMES))
    order_b = _deck(
        *[_card(n, evo=1 if n == "Valkyrie" else 0, rarity="rare" if n == "Valkyrie" else "common")
          for n in order_b_names]
    )
    # Many games in order A without evo
    merged = merge_deck_variants([order_a, order_a, order_a, order_b])
    by_name = {c["name"]: c for c in merged}
    assert by_name["Valkyrie"]["evolution_level"] == 1


def test_or_merge_profile_does_not_wipe_battle_evo():
    profile = _deck(*[_card(n) for n in NAMES])
    battles = _deck(
        _card("Valkyrie", evo=1, rarity="rare"),
        *[_card(n) for n in NAMES[1:]],
    )
    combined = or_merge_modes_onto(profile, [profile, battles], clamp=False)
    by_name = {c["name"]: c for c in combined}
    assert by_name["Valkyrie"]["evolution_level"] == 1
    assert [c["name"] for c in combined] == NAMES


def test_upgrade_score_ignores_plain_icons():
    base = _deck(*[_card(n) | {"icon": "http://x"} for n in NAMES])
    evo = _deck(_card("Valkyrie", evo=1, rarity="rare"), *[_card(n) for n in NAMES[1:]])
    assert deck_upgrade_score(base) == 0
    assert deck_upgrade_score(evo) > deck_upgrade_score(base)


def test_display_or_merge_does_not_demote_cross_loadout_specials():
    """Historical union may exceed legal slot budget — keep all seen modes for display."""
    names = [
        "Balloon", "Berserker", "Musketeer", "Bats",
        "Giant Snowball", "Bomb Tower", "Barbarian Barrel", "Mighty Miner",
    ]
    loadout_a = _deck(
        _card("Balloon", hero=True, rarity="epic"),
        _card("Berserker", hero=True, rarity="common"),
        _card("Musketeer", rarity="rare"),
        *[_card(n, rarity="champion" if n == "Mighty Miner" else "common") for n in names[3:]],
    )
    loadout_b = _deck(
        _card("Balloon", rarity="epic"),
        _card("Berserker", rarity="common"),
        _card("Musketeer", evo=1, rarity="rare"),
        *[_card(n, rarity="champion" if n == "Mighty Miner" else "common") for n in names[3:]],
    )
    merged = or_merge_modes_onto(loadout_a, [loadout_a, loadout_b], clamp=False)
    by_name = {c["name"]: c for c in merged}
    assert by_name["Balloon"]["is_hero"] is True
    assert by_name["Berserker"]["is_hero"] is True
    assert by_name["Musketeer"]["evolution_level"] == 1


def test_serialize_roundtrip_preserves_modes():
    deck = _deck(
        _card("Balloon", hero=True, rarity="epic"),
        _card("Berserker", hero=True, rarity="common"),
        *[_card(n) for n in NAMES[2:]],
    )
    restored = parse_deck_cards_json(serialize_deck_cards(deck))
    assert len(restored) == 8
    by_name = {c["name"]: c for c in restored}
    assert by_name["Balloon"]["is_hero"] is True
    assert by_name["Berserker"]["is_hero"] is True


def test_cards_from_team_accepts_restored_cache_cards():
    from bot.services.card_icons import cards_from_team

    deck = _deck(
        _card("Balloon", hero=True, rarity="epic"),
        *[_card(n) for n in NAMES[1:]],
    )
    team = {"cards": deck}
    parsed = cards_from_team(team)
    assert len(parsed) == 8
    assert parsed[0]["is_hero"] is True
    assert parsed[0]["name"] == "Balloon"
