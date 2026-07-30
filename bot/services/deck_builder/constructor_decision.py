"""Слой решений конструктора: DeckIntent → GamePlan → bias шаблонов.

Не заменяет finalize/scoring — только порядок и приоритет выбора шаблона.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.services.card_data import card_has_role, get_card_elixir
from bot.services.deck_builder.loader import DeckRecord
from bot.services.deck_game_plan import GamePlan, build_game_plan
from bot.services.deck_intent import DeckIntent, DeckIntentEngine


def _is_cycle_card(name: str) -> bool:
    return card_has_role(name, "cycle") or get_card_elixir(name) <= 2


@dataclass(frozen=True)
class ConstructorDecision:
    """Контекст решений для одной сборки из core."""

    archetype: str
    intent: DeckIntent
    game_plan: GamePlan


def prepare_constructor_decision(
    core: list[str],
    *,
    detect_archetype,
) -> ConstructorDecision:
    """1) DeckIntent  2) GamePlan — до выбора шаблона."""
    archetype = detect_archetype(core)
    intent = DeckIntentEngine.infer(core, archetype=archetype)
    # Архетип из intent (после infer) — единый для шагов 3–6
    archetype = intent.archetype
    game_plan = build_game_plan(core, archetype=archetype, intent=intent)
    return ConstructorDecision(
        archetype=archetype,
        intent=intent,
        game_plan=game_plan,
    )


def template_decision_bonus(record: DeckRecord, decision: ConstructorDecision) -> float:
    """Доп. очки шаблона относительно Intent/GamePlan (не ломает базовый score)."""
    bonus = 0.0
    cards = set(record.cards)
    intent = decision.intent
    plan = decision.game_plan

    if record.archetype == decision.archetype:
        bonus += 10.0
    if intent.primary_win and intent.primary_win in cards:
        bonus += 12.0

    key_hits = len(cards & set(plan.key_cards))
    bonus += min(14.0, key_hits * 3.5)

    # Комбинации плана: обе карты пары в шаблоне
    for combo in plan.core_combinations[:3]:
        parts = [p.strip() for p in combo.split("+")]
        if len(parts) == 2 and parts[0] in cards and parts[1] in cards:
            bonus += 4.0

    if intent.require_building:
        if any(card_has_role(c, "building") for c in record.cards):
            bonus += 5.0
        else:
            bonus -= 6.0

    if intent.min_cycle_cards > 0:
        cycle_n = sum(1 for c in record.cards if _is_cycle_card(c))
        if cycle_n >= intent.min_cycle_cards:
            bonus += 4.0

    if intent.min_air_defense > 0:
        air_n = sum(1 for c in record.cards if card_has_role(c, "air_defense"))
        if air_n >= intent.min_air_defense:
            bonus += 3.0

    return bonus


def result_decision_bonus(deck: list[str], decision: ConstructorDecision) -> float:
    """Подстройка финального ранжирования собранных колод."""
    bonus = 0.0
    cards = set(deck)
    intent = decision.intent
    plan = decision.game_plan

    if intent.primary_win and intent.primary_win in cards:
        bonus += 8.0

    bonus += min(10.0, len(cards & set(plan.key_cards)) * 2.0)

    for combo in plan.core_combinations[:3]:
        parts = [p.strip() for p in combo.split("+")]
        if len(parts) == 2 and parts[0] in cards and parts[1] in cards:
            bonus += 3.0

    # Штраф, если план требует здание, а в итоге его нет
    if intent.require_building and not any(card_has_role(c, "building") for c in deck):
        bonus -= 8.0

    return bonus
