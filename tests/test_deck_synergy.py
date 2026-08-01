"""Регрессии новой модели синергии колоды."""

from bot.services.card_matchups import calculate_deck_synergy
from bot.services.deck_synergy import evaluate_deck_synergy


def test_executioner_tornado_is_strong():
    score, notes = calculate_deck_synergy(["Executioner", "Tornado"])
    joined = " ".join(notes)
    assert score >= 65
    assert "Палач" in joined or "Торнадо" in joined


def test_lava_balloon_is_strong():
    score, notes = calculate_deck_synergy(["Lava Hound", "Balloon"])
    joined = " ".join(notes)
    assert score >= 70
    assert "Лава" in joined or "Шар" in joined or "Balloon" in joined or "Lava" in joined


def test_goblin_barrel_princess_is_strong():
    score, notes = calculate_deck_synergy(["Goblin Barrel", "Princess"])
    joined = " ".join(notes)
    assert score >= 70
    assert "Бочк" in joined or "Принцесс" in joined


def test_hog_cycle_not_artificially_low():
    deck = [
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ]
    score, _notes = calculate_deck_synergy(deck)
    assert score >= 55
    assert score > 30


def test_conflicting_heavy_wins_score_below_coherent_cycle():
    conflict = [
        "Golem", "Lava Hound", "Baby Dragon", "Mega Minion",
        "Lightning", "Tornado", "Barbarian Barrel", "Night Witch",
    ]
    cycle = [
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ]
    conflict_score = evaluate_deck_synergy(conflict).score
    cycle_score = evaluate_deck_synergy(cycle).score
    assert cycle_score > conflict_score
    assert conflict_score < cycle_score - 5


def test_full_exenado_control_keeps_core_note():
    deck = [
        "Royal Giant", "Fisherman", "Executioner", "Tornado",
        "Electro Spirit", "Skeletons", "The Log", "Lightning",
    ]
    evaluation = evaluate_deck_synergy(deck)
    joined = " ".join(evaluation.notes)
    assert evaluation.score >= 60
    assert "Палач" in joined and "Торнадо" in joined
    assert evaluation.breakdown.core > 0
