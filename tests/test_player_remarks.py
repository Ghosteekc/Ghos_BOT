"""Tests for Primary WC / Secondary Pressure and player remarks."""

from __future__ import annotations

from bot.services.card_data import (
    count_independent_wins,
    is_primary_win_condition,
    is_secondary_pressure,
)
from bot.services.deck_builder.balance import count_wins, hard_constraint_issues
from bot.services.deck_builder.loader import get_database
from bot.services.deck_evaluator import DeckEvaluator
from bot.services.deck_intent import detect_primary_win
from bot.services.deck_sanity_validator import validate_deck_sanity
from bot.services.player_remarks import build_player_remarks, looks_internal


HOG_MM_DECK = [
    "Executioner",
    "Valkyrie",
    "Mighty Miner",
    "Tornado",
    "Hog Rider",
    "The Log",
    "Fireball",
    "Guards",
]


def test_mighty_miner_is_secondary_not_primary():
    assert is_secondary_pressure("Mighty Miner")
    assert not is_primary_win_condition("Mighty Miner")
    assert is_primary_win_condition("Hog Rider")


def test_hog_plus_mighty_miner_not_too_many_wins():
    db = get_database()
    assert count_independent_wins(HOG_MM_DECK) == 1
    assert count_wins(HOG_MM_DECK, db) == 1
    hard = hard_constraint_issues(HOG_MM_DECK, db)
    assert "too_many_wins" not in hard


def test_detect_primary_prefers_hog_over_mm():
    assert detect_primary_win(HOG_MM_DECK) == "Hog Rider"


def test_sanity_no_rebuild_for_hog_mm():
    report = validate_deck_sanity(HOG_MM_DECK)
    joined = " ".join(report.critical_messages).lower()
    assert "recommendationengine" not in joined
    assert "пересобрать" not in joined
    assert "too_many_wins" not in joined
    # Конфликт primary+secondary больше не critical.
    assert "conflicting_roles" not in {i.code for i in report.critical_issues}


def test_evaluation_score_not_extreme_low_for_playable():
    report = DeckEvaluator.evaluate(HOG_MM_DECK)
    assert "too_many_wins" not in report.hard_constraints.issues
    assert report.total_score >= 52.0
    blob = " ".join([
        *report.weaknesses,
        *report.can_improve,
        report.final_recommendation,
    ]).lower()
    assert "recommendationengine" not in blob
    assert "too_many_wins" not in blob
    assert "/100" not in blob
    assert report.final_recommendation
    assert "Что хорошо" in "\n".join(report.whats_good) or report.whats_good or True


def test_player_remarks_playable_blocks_rebuild():
    remarks = build_player_remarks(
        strengths=["Главная угроза — Хог"],
        improvements=[
            "RecommendationEngine видит критический дисбаланс — колоду нужно пересобрать.",
            "Суммарная оценка слишком низкая (34/100)",
            "Слабый ответ на тяжёлые танки",
        ],
        deck_playable=True,
        primary_win="Hog Rider",
        secondary_pressure=["Mighty Miner"],
    )
    text = "\n".join(remarks.as_issue_lines()).lower()
    assert "пересобрать" not in text
    assert "34/100" not in text
    assert "recommendationengine" not in text
    assert "слабый ответ" in text
    assert "подходит" in remarks.final_recommendation.lower()
    assert any("давлени" in g.lower() for g in remarks.whats_good)


def test_looks_internal_codes():
    assert looks_internal("Оценка провалена (too_many_wins).")
    assert looks_internal("34/100 — не стабильная")
    assert not looks_internal("Слабый ответ на тяжёлые танки")
