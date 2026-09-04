"""Mine deck matchup reasons: snapshot-backed counters and no cycle advice."""

from __future__ import annotations

from bot.services.deck_detail import (
    _effective_counters,
    _skip_counter_advice,
    _suggested_counters,
)


HOG_2_6 = [
    "Hog Rider",
    "Musketeer",
    "Ice Spirit",
    "Skeletons",
    "Cannon",
    "Fireball",
    "The Log",
    "Ice Golem",
]


def test_skip_counter_advice_for_larry_and_spirits() -> None:
    assert _skip_counter_advice("Skeletons")
    assert _skip_counter_advice("Ice Spirit")
    assert _skip_counter_advice("Electro Spirit")
    assert not _skip_counter_advice("Goblin Barrel")
    assert not _skip_counter_advice("Tesla")


def test_no_effective_counters_for_cycle_fodder() -> None:
    assert _effective_counters(HOG_2_6, "Skeletons") == []
    assert _effective_counters(HOG_2_6, "Ice Spirit") == []
    assert _suggested_counters("Skeletons") == []


def test_deckshop_building_answers_are_used_without_win_condition_filter() -> None:
    assert "Hog Rider" in _effective_counters(HOG_2_6, "Tesla")
    assert "Hog Rider" in _effective_counters(HOG_2_6, "Cannon")


def test_real_answers_still_work() -> None:
    # Log bait pieces: Goblin Barrel → Log is a real answer.
    assert "The Log" in _effective_counters(HOG_2_6, "Goblin Barrel")
    # Building removal spell is a valid suggestion.
    assert "Earthquake" in _suggested_counters("Tesla") or "Fireball" in _suggested_counters(
        "Tesla"
    )
