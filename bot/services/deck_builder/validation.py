"""Финальная валидация вариантов Builder.

Этот модуль не выбирает и не меняет карты. Он отвечает на один вопрос:
достаточно ли стабилен уже собранный вариант, чтобы Builder мог вернуть его
пользователю. Если нет, Builder обязан отбросить вариант и построить другой.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.services.deck_builder.balance import ScoreBreakdown, compute_score_breakdown
from bot.services.deck_builder.constants import (
    ROLE_ANTI_TANK,
    ROLE_DEFENSIVE,
    ROLE_DPS,
    ROLE_MINI_TANK,
)
from bot.services.deck_builder.loader import DeckDatabase
from bot.services.deck_builder.win_plan_check import WinPlanCheck, evaluate_win_plan
from bot.services.deck_intent import DeckIntent


@dataclass(frozen=True)
class BuilderValidation:
    """Все обязательные проверки одного итогового варианта."""

    balance: bool
    synergy: bool
    counter_coverage: bool
    win_condition: bool
    air_defense: bool
    ground_defense: bool
    cycle: bool
    spell_balance: bool
    building: bool
    archetype_identity: bool
    deck_identity: bool
    win_plan: WinPlanCheck
    score_breakdown: ScoreBreakdown
    issues: list[str]

    @property
    def stable(self) -> bool:
        return not self.issues


def validate_builder_variant(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    *,
    archetype: str,
    intent: DeckIntent,
    required_roles: frozenset[str],
    mandatory_cards: frozenset[str],
    pair_synergy,
) -> BuilderValidation:
    """Проверить готовую колоду по обязательному checklist Builder.

    Роли не изобретаются: используются только существующие roles[] и
    ScoreBreakdown. ``counter_coverage`` — агрегат защиты от воздуха, роя и
    тяжёлых целей, а не отдельный второй рекомендатель.
    """
    breakdown = compute_score_breakdown(
        deck,
        db,
        core,
        archetype,
        pair_synergy=pair_synergy,
    )
    win_plan = evaluate_win_plan(deck, db, archetype, intent=intent)
    roles = {
        role: any(db.get_card(card) and role in db.get_card(card).roles for card in deck)
        for role in required_roles
    }
    has_ground_defense = any(
        db.get_card(card)
        and (
            ROLE_DEFENSIVE in db.get_card(card).roles
            or ROLE_MINI_TANK in db.get_card(card).roles
            or ROLE_ANTI_TANK in db.get_card(card).roles
            or ROLE_DPS in db.get_card(card).roles
        )
        for card in deck
    )

    checks = {
        "balance": (
            not breakdown.hard_issues
            and breakdown.total >= 52.0
            and not {"elixir", "big_spell", "small_spell"} & set(breakdown.soft_issues)
        ),
        "synergy": breakdown.synergy >= 30.0,
        "counter_coverage": (
            breakdown.anti_air >= 50.0
            and breakdown.anti_swarm >= 55.0
            and breakdown.defense >= 30.0
        ),
        "win_condition": win_plan.primary_win,
        "air_defense": breakdown.anti_air >= 50.0,
        "ground_defense": has_ground_defense,
        "cycle": "cycle" not in breakdown.soft_issues,
        "spell_balance": (
            breakdown.spell_balance >= 55.0
            and not {"big_spell", "small_spell"} & set(breakdown.soft_issues)
        ),
        "building": (
            not intent.require_building or "building" not in breakdown.soft_issues
        ),
        "archetype_identity": breakdown.archetype_fit >= 35.0 or archetype in {"Meta", "Control"},
        "deck_identity": (
            set(mandatory_cards).issubset(deck)
            and all(roles.values())
        ),
        "win_plan": win_plan.complete,
    }
    issues = [name for name, ok in checks.items() if not ok]
    return BuilderValidation(
        balance=checks["balance"],
        synergy=checks["synergy"],
        counter_coverage=checks["counter_coverage"],
        win_condition=checks["win_condition"],
        air_defense=checks["air_defense"],
        ground_defense=checks["ground_defense"],
        cycle=checks["cycle"],
        spell_balance=checks["spell_balance"],
        building=checks["building"],
        archetype_identity=checks["archetype_identity"],
        deck_identity=checks["deck_identity"],
        win_plan=win_plan,
        score_breakdown=breakdown,
        issues=issues,
    )
