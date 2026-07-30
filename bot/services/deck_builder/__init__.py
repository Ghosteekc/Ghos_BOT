"""Публичный API deck_builder.

Импорты balance/builder — ленивые: иначе package init тянет card_matchups
во время загрузки loader → отравление CardProfile (см. card_profile.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.services.deck_builder.loader import DeckDatabase, get_database

if TYPE_CHECKING:
    from bot.services.deck_builder.balance import ScoreBreakdown
    from bot.services.deck_builder.builder import BuildResult

__all__ = [
    "BuildResult",
    "DeckDatabase",
    "ScoreBreakdown",
    "build_deck_from_core",
    "build_multiple_decks",
    "compute_score_breakdown",
    "get_database",
    "hard_constraint_issues",
    "soft_balance_issues",
]


def __getattr__(name: str):
    if name in {"ScoreBreakdown", "compute_score_breakdown", "hard_constraint_issues", "soft_balance_issues"}:
        from bot.services.deck_builder import balance as _balance

        return getattr(_balance, name)
    if name in {"BuildResult", "build_deck_from_core", "build_multiple_decks"}:
        from bot.services.deck_builder import builder as _builder

        return getattr(_builder, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
