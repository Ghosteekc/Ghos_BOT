"""Единый источник истины качества колоды (Builder SoT).

Владеет:
- EvaluationReport (через DeckEvaluator)
- определением «хорошая колода»
- подсчётом независимых win conditions

Recommendation / Improver / Analyzer / Matchup / Sanity не считают
собственный total_score / balanced / wins — только читают отсюда.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bot.services.deck_builder.constraint_messages import (
    GOOD_DECK_MIN_TOTAL,
    HARD_MESSAGES,
    SOFT_MESSAGES,
)

if TYPE_CHECKING:
    from bot.services.deck_builder.loader import DeckDatabase
    from bot.services.deck_evaluator.models import EvaluationReport

__all__ = [
    "GOOD_DECK_MIN_TOTAL",
    "HARD_MESSAGES",
    "SOFT_MESSAGES",
    "BalanceIssuesView",
    "balance_issues_from_report",
    "count_wins",
    "evaluate_deck",
    "is_good_deck",
    "message_for_hard",
    "message_for_soft",
]


@dataclass(frozen=True)
class BalanceIssuesView:
    """Срез hard/soft из EvaluationReport (без пересчёта)."""

    hard: list[str]
    soft: list[str]
    messages: list[str]


def evaluate_deck(
    deck: list[str],
    *,
    core: list[str] | None = None,
    archetype: str | None = None,
    opponent: list[str] | None = None,
    db: "DeckDatabase | None" = None,
) -> "EvaluationReport":
    """Единственная точка оценки колоды → EvaluationReport."""
    from bot.services.deck_evaluator.evaluator import DeckEvaluator

    return DeckEvaluator.evaluate(
        deck,
        core=core,
        archetype=archetype,
        opponent=opponent,
        db=db,
    )


def is_good_deck(
    deck: list[str] | None = None,
    *,
    report: "EvaluationReport | None" = None,
    core: list[str] | None = None,
    archetype: str | None = None,
    db: "DeckDatabase | None" = None,
) -> bool:
    """Единственное определение: хорошая колода.

    hard_constraints.passed и total_score >= GOOD_DECK_MIN_TOTAL.
    """
    evaluation = report
    if evaluation is None:
        if deck is None:
            return False
        evaluation = evaluate_deck(deck, core=core, archetype=archetype, db=db)
    return (
        evaluation.hard_constraints.passed
        and evaluation.total_score >= GOOD_DECK_MIN_TOTAL
    )


def count_wins(deck: list[str], db: "DeckDatabase | None" = None) -> int:
    """Независимые WC (Primary; Secondary не дублирует)."""
    from bot.services.deck_builder.balance import count_wins as _count
    from bot.services.deck_builder.loader import get_database

    return _count(deck, db or get_database())


def balance_issues_from_report(report: "EvaluationReport") -> BalanceIssuesView:
    """Hard/soft/messages только из EvaluationReport — без локального пересчёта."""
    hard = list(report.hard_constraints.issues)
    soft = list(report.soft_constraints.issues)
    messages = list(report.hard_constraints.messages) + list(report.soft_constraints.messages)
    return BalanceIssuesView(hard=hard, soft=soft, messages=messages)


def message_for_hard(key: str) -> str:
    return HARD_MESSAGES.get(key, "Есть проблема с балансом колоды")


def message_for_soft(key: str) -> str:
    return SOFT_MESSAGES.get(key, "Есть слабое место в составе")
