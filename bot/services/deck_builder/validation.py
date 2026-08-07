"""Финальная валидация вариантов Builder.

Этот модуль не выбирает и не меняет карты. Он отвечает на один вопрос:
достаточно ли стабилен уже собранный вариант, чтобы Builder мог вернуть его
пользователю. Если нет, Builder обязан отбросить вариант и построить другой.

Единственный источник числовой оценки — EvaluationReport (DeckEvaluator).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from bot.services.deck_builder.constants import (
    ROLE_ANTI_TANK,
    ROLE_COUNTERPUSH,
    ROLE_CYCLE,
    ROLE_DEFENSIVE,
    ROLE_DPS,
    ROLE_MINI_TANK,
    ROLE_SUPPORT,
)
from bot.services.deck_builder.loader import DeckDatabase
from bot.services.deck_builder.win_plan_check import WinPlanCheck, evaluate_win_plan
from bot.services.deck_evaluator import EvaluationReport
from bot.services.deck_evaluator.evaluator import DeckEvaluator
from bot.services.deck_game_plan import build_game_plan
from bot.services.deck_intent import DeckIntent

_COMBO_WIN_PAIRS = frozenset({
    frozenset({"Lava Hound", "Balloon"}),
})
_FAST_CYCLE_WINS = frozenset({
    "Hog Rider", "Goblin Barrel", "X-Bow", "Mortar", "Wall Breakers", "Miner",
})


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
    evaluation: EvaluationReport
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
    primary_anchor: str | None = None,
) -> BuilderValidation:
    """Проверить готовую колоду по обязательному checklist Builder.

    Роли не изобретаются: используются только существующие roles[] и
    EvaluationReport. ``counter_coverage`` — агрегат защиты от воздуха, роя и
    тяжёлых целей из evaluation.matchup_coverage.
    """
    del required_roles  # сигнал Intent; покрытие ролей уже в EvaluationReport

    evaluation = DeckEvaluator.evaluate(
        deck,
        core=core,
        archetype=archetype,
        db=db,
    )

    # Если пользователь положил win condition в core, это не просто одна из
    # карт: принудительно проверяем план именно вокруг неё.
    plan_intent = replace(intent, archetype=archetype, primary_win=primary_anchor) if primary_anchor else None
    win_plan = evaluate_win_plan(deck, db, archetype, intent=plan_intent)
    game_plan = build_game_plan(deck, archetype=archetype, intent=plan_intent)
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
    has_anti_tank = any(
        db.get_card(card) and ROLE_ANTI_TANK in db.get_card(card).roles
        for card in deck
    )
    cycle_n = sum(
        1
        for card in deck
        if (
            db.get_card(card)
            and ROLE_CYCLE in db.get_card(card).roles
        )
        or (db.get_card(card).elixir if db.get_card(card) else 4) <= 2
    )
    primary = win_plan.primary_card
    has_win_support = bool(primary) and any(
        card != primary
        and db.get_card(card)
        and (
            ROLE_SUPPORT in db.get_card(card).roles
            or ROLE_DPS in db.get_card(card).roles
            or ROLE_COUNTERPUSH in db.get_card(card).roles
        )
        for card in deck
    )
    if primary and not has_win_support:
        has_win_support = any(
            card != primary and pair_synergy(primary, card) >= 72
            for card in deck
        )
    wins = {
        card for card in deck
        if db.get_card(card) and "win_condition" in db.get_card(card).roles
    }
    allows_combo_wins = any(pair <= wins for pair in _COMBO_WIN_PAIRS)
    selected_core_wins = wins <= set(core)

    hard_issues = set(evaluation.hard_constraints.issues)
    if allows_combo_wins or selected_core_wins:
        hard_issues.discard("too_many_wins")
    soft_issues = set(evaluation.soft_constraints.issues)

    details = evaluation.matchup_coverage.details
    anti_air = float(details.get("anti_air", evaluation.matchup_coverage.score))
    anti_swarm = float(details.get("anti_swarm", evaluation.matchup_coverage.score))
    defense = float(details.get("defense", evaluation.matchup_coverage.score))

    anchor_present = not primary_anchor or primary_anchor in deck
    anchor_is_primary = not primary_anchor or win_plan.primary_card == primary_anchor
    # primary_threat — человекочитаемая RU-строка; якорь сверяем по key_cards
    # (английские имена), иначе startswith(EN) ломает все сборки после локализации.
    anchor_plan_matches = (
        not primary_anchor
        or (
            bool(game_plan.key_cards)
            and game_plan.key_cards[0] == primary_anchor
        )
    )
    anchor_pressure = (
        not primary_anchor
        or (
            cycle_n >= 2
            if primary_anchor in _FAST_CYCLE_WINS
            else win_plan.constant_pressure and win_plan.counterattack
        )
    )

    checks = {
        "balance": (
            not hard_issues
            and evaluation.total_score >= 52.0
            and not {"elixir", "big_spell", "small_spell"} & soft_issues
        ),
        "synergy": evaluation.synergy.score >= 30.0,
        "counter_coverage": (
            anti_air >= 50.0
            and anti_swarm >= 55.0
            and defense >= 30.0
        ),
        "win_condition": win_plan.primary_win,
        "primary_anchor": anchor_present and anchor_is_primary,
        "anchor_pressure": anchor_pressure,
        "anchor_game_plan": anchor_plan_matches,
        "win_support": has_win_support,
        "air_defense": anti_air >= 50.0,
        "ground_defense": has_ground_defense,
        "anti_tank": has_anti_tank,
        # Не навязываем искусственно два cycle-слота, но у готовой колоды
        # всегда должен быть хотя бы один способ вернуть давление в руку.
        "cycle": cycle_n >= 1,
        "spell_balance": (
            evaluation.spell_balance.score >= 55.0
            and not {"big_spell", "small_spell"} & soft_issues
        ),
        "building": (
            not intent.require_building or "building" not in soft_issues
        ),
        # Архетип — ранжирующий сигнал, не причина отклонить завершённую
        # стратегию с тем же core.
        "archetype_identity": True,
        "deck_identity": (
            set(mandatory_cards).issubset(deck)
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
        evaluation=evaluation,
        issues=issues,
    )
