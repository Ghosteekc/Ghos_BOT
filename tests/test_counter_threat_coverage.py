"""Counter threat coverage: reliable anti-air vs critical air threats."""

from __future__ import annotations

from bot.services.card_data import CARD_META
from bot.services.counter_engine import suggest_counter_deck
from bot.services.counter_threat_coverage import (
    evaluate_threat_coverage,
    is_critical_air_threat,
    is_reliable_air_defense,
    repair_critical_air_gap,
    reliable_air_defense_in_deck,
)


# User-reported invalid counter vs Electro Dragon (Speedy Miner = Mighty Miner).
INVALID_AIR_COUNTER = [
    "Hog Rider",
    "Mighty Miner",
    "Arrows",
    "Valkyrie",
    "Tornado",
    "The Log",
    "Fireball",
    "Bomb Tower",
]

ENEMY_WITH_EDRAG = [
    "Electro Dragon",
    "Giant",
    "Night Witch",
    "Bomber",
    "Barbarian Barrel",
    "Lightning",
    "Guards",
    "Tornado",
]

GOOD_AIR_COUNTER = [
    "Hog Rider",
    "Musketeer",
    "Ice Spirit",
    "Skeletons",
    "Cannon",
    "Fireball",
    "The Log",
    "Ice Golem",
]


def test_edrag_is_critical_air_threat() -> None:
    assert is_critical_air_threat("Electro Dragon")
    assert is_critical_air_threat("Balloon")
    assert not is_critical_air_threat("Bats")  # soft air only
    assert not is_critical_air_threat("Valkyrie")


def test_spells_are_not_reliable_air_defense() -> None:
    for spell in ("Arrows", "Fireball", "Tornado", "The Log", "Zap"):
        assert not is_reliable_air_defense(spell), spell
    assert not is_reliable_air_defense("Valkyrie")
    assert not is_reliable_air_defense("Bomb Tower")
    assert is_reliable_air_defense("Musketeer")
    assert is_reliable_air_defense("Tesla")
    assert is_reliable_air_defense("Archers")


def test_invalid_counter_vs_edrag_fails_coverage() -> None:
    report = evaluate_threat_coverage(INVALID_AIR_COUNTER, ENEMY_WITH_EDRAG)
    assert report.is_valid is False
    assert any("air" in r.lower() for r in report.reasons)
    assert not report.reliable_air_defense
    assert any(t.card == "Electro Dragon" for t in report.uncovered_threats)


def test_spell_only_air_coverage_is_insufficient() -> None:
    spell_only = [
        "Hog Rider",
        "Knight",
        "Arrows",
        "Fireball",
        "Tornado",
        "The Log",
        "Ice Golem",
        "Cannon",
    ]
    report = evaluate_threat_coverage(spell_only, ["Electro Dragon"] + ENEMY_WITH_EDRAG[1:])
    assert report.is_valid is False
    assert not reliable_air_defense_in_deck(spell_only)


def test_repair_adds_reliable_air_without_duplicates() -> None:
    pool = set(CARD_META.keys())
    ranked = [
        (9.0, "Musketeer"),
        (8.0, "Archers"),
        (7.5, "Tesla"),
        (6.0, "Mega Minion"),
    ]
    fixed, swaps = repair_critical_air_gap(
        list(INVALID_AIR_COUNTER),
        ENEMY_WITH_EDRAG,
        pool=pool,
        ranked=ranked,
    )
    assert swaps
    assert len(fixed) == 8
    assert len(set(fixed)) == 8
    assert reliable_air_defense_in_deck(fixed)
    assert "Hog Rider" in fixed  # win condition preserved
    report = evaluate_threat_coverage(fixed, ENEMY_WITH_EDRAG)
    assert report.is_valid is True


def test_good_air_counter_needs_no_repair() -> None:
    report = evaluate_threat_coverage(GOOD_AIR_COUNTER, ENEMY_WITH_EDRAG)
    assert report.is_valid is True
    assert "Musketeer" in report.reliable_air_defense

    pool = set(CARD_META.keys())
    ranked = [(9.0, "Archers"), (8.0, "Tesla")]
    fixed, swaps = repair_critical_air_gap(
        list(GOOD_AIR_COUNTER),
        ENEMY_WITH_EDRAG,
        pool=pool,
        ranked=ranked,
    )
    assert swaps == []
    assert fixed == GOOD_AIR_COUNTER


def test_repair_respects_arena_pool() -> None:
    # Mid-arena style pool without Musketeer — Tesla/Archers still OK.
    pool = {
        "Hog Rider",
        "Mighty Miner",
        "Arrows",
        "Valkyrie",
        "Tornado",
        "The Log",
        "Fireball",
        "Bomb Tower",
        "Archers",
        "Tesla",
        "Knight",
        "Cannon",
        "Zap",
        "Giant",
        "Electro Dragon",
        "Night Witch",
        "Bomber",
        "Barbarian Barrel",
        "Lightning",
        "Guards",
    }
    ranked = [(5.0, "Archers"), (4.5, "Tesla")]
    fixed, swaps = repair_critical_air_gap(
        list(INVALID_AIR_COUNTER),
        ENEMY_WITH_EDRAG,
        pool=pool,
        ranked=ranked,
    )
    assert swaps
    assert swaps[0]["pick"] in pool
    assert swaps[0]["pick"] not in {"Musketeer"}  # not in pool
    assert is_reliable_air_defense(swaps[0]["pick"])


def test_suggest_counter_deck_repairs_air_gap() -> None:
    """End-to-end: adapting the invalid deck vs Edrag must yield reliable AA."""
    out = suggest_counter_deck(
        ENEMY_WITH_EDRAG,
        arena_id=54000056,
        preferred_cards=[],
        user_deck=list(INVALID_AIR_COUNTER),
        trophies=8000,
    )
    assert len(out) == 8
    assert len(set(out)) == 8
    assert reliable_air_defense_in_deck(out)
    report = evaluate_threat_coverage(out, ENEMY_WITH_EDRAG)
    assert report.is_valid is True


def test_suggest_counter_keeps_existing_good_air() -> None:
    out = suggest_counter_deck(
        ENEMY_WITH_EDRAG,
        arena_id=54000056,
        preferred_cards=[],
        user_deck=list(GOOD_AIR_COUNTER),
        trophies=8000,
    )
    assert "Musketeer" in out or reliable_air_defense_in_deck(out)
    # Should not strip Hog
    assert "Hog Rider" in out
