"""OR-merge of evolution/hero across cache stubs and alternate orders."""
from __future__ import annotations

from bot.services.card_icons import deck_upgrade_score, merge_deck_variants, or_merge_modes_onto


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
    combined = or_merge_modes_onto(profile, [profile, battles])
    by_name = {c["name"]: c for c in combined}
    assert by_name["Valkyrie"]["evolution_level"] == 1
    assert [c["name"] for c in combined] == NAMES


def test_upgrade_score_ignores_plain_icons():
    base = _deck(*[_card(n) | {"icon": "http://x"} for n in NAMES])
    evo = _deck(_card("Valkyrie", evo=1, rarity="rare"), *[_card(n) for n in NAMES[1:]])
    assert deck_upgrade_score(base) == 0
    assert deck_upgrade_score(evo) > deck_upgrade_score(base)
