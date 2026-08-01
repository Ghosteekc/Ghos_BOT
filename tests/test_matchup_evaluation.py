"""Регрессии единого источника оценки матчапа."""

from bot.services.battle_report import analyze_battle_enhanced
from bot.services.deck_analyzer import analyze_battle, calculate_matchup_score
from bot.services.match_difficulty import MatchDifficultyAnalyzer
from bot.services.matchup_evaluation import evaluate_matchup, rating_for


def _deck(names: list[str]) -> list[str]:
    assert len(names) == 8
    return names


def test_evaluation_bands_are_single_source_of_truth():
    assert rating_for(0) == "Очень лёгкий"
    assert rating_for(20) == "Очень лёгкий"
    assert rating_for(21) == "Лёгкий"
    assert rating_for(40) == "Лёгкий"
    assert rating_for(41) == "Равный"
    assert rating_for(60) == "Равный"
    assert rating_for(61) == "Сложный"
    assert rating_for(80) == "Сложный"
    assert rating_for(81) == "Очень сложный"


def test_score_and_difficulty_are_same_evaluation():
    user = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Fireball",
        "Ice Spirit", "Skeletons", "The Log", "Cannon",
    ])
    opponent = _deck([
        "Balloon", "Lava Hound", "Baby Dragon", "Mega Minion",
        "Tesla", "Cannon", "Zap", "Arrows",
    ])

    evaluation = evaluate_matchup(user, opponent)
    difficulty = MatchDifficultyAnalyzer.analyze(user, opponent)
    assert evaluation.score == evaluation.difficulty == difficulty.difficulty
    assert evaluation.rating == difficulty.rating
    assert calculate_matchup_score(user, opponent) == evaluation.score
    assert evaluation.reasons
    assert all(
        contribution.delta > 0
        for contribution in evaluation.contributions
        if contribution.reason in evaluation.reasons
    )


def test_very_hard_matchup_never_gets_favorable_language():
    user_deck = _deck([
        "Hog Rider", "Ice Golem", "Knight", "Skeletons",
        "Ice Spirit", "The Log", "Fireball", "Cannon",
    ])
    opponent_deck = _deck([
        "Balloon", "Lava Hound", "Baby Dragon", "Mega Minion",
        "Tesla", "Cannon", "Zap", "Arrows",
    ])
    user = {
        "name": "Игрок",
        "crowns": 0,
        "cards": [{"name": name} for name in user_deck],
    }
    opponent = {
        "name": "Соперник",
        "crowns": 1,
        "cards": [{"name": name} for name in opponent_deck],
    }

    evaluation = evaluate_matchup(user_deck, opponent_deck)
    assert evaluation.rating == "Очень сложный"

    base = analyze_battle(user, opponent)
    detailed = analyze_battle_enhanced(user, opponent)
    text = " ".join(base.reasons + detailed.reasons + [detailed.outcome_summary]).lower()
    assert "благоприят" not in text
    assert "неблагоприят" not in text
    assert "удачный матчап" not in text
    assert detailed.match_difficulty is not None
    assert detailed.matchup_score == detailed.match_difficulty.difficulty
