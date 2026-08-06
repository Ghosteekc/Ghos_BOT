"""DeckIntentEngine — стратегия колоды для анализа soft-ролей.

Не заменяет builder/scoring. Даёт required/optional ожидания по архетипу,
чтобы soft_balance_issues и passport-слабости не использовали один
универсальный чек-лист для всех колод.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.services.card_data import (
    WIN_CONDITIONS,
    is_primary_win_condition,
    is_secondary_pressure,
    is_tower_threat,
)
from bot.services.card_profile import get_card_profile

# Soft-issue keys, совместимые с soft_balance_issues / FE balanceIssues.
SoftCheck = str


@dataclass(frozen=True)
class DeckIntent:
    archetype: str
    play_style: str
    primary_win: str | None
    """Soft-check ids that missing → issue (big_spell, air_defense, …)."""
    required_soft_checks: frozenset[SoftCheck]
    min_air_defense: int
    require_building: bool
    min_cycle_cards: int
    """Role-balance ids from passport checklist that are strategic for this style."""
    required_role_ids: frozenset[str]
    attack_bias: float


@dataclass(frozen=True)
class _ArchetypePolicy:
    play_style: str
    required_soft_checks: frozenset[str]
    min_air_defense: int
    require_building: bool
    min_cycle_cards: int
    required_role_ids: frozenset[str]
    attack_bias: float


# Политики: что обязательно для стратегии (не «идеальная универсальная колода»).
_POLICIES: dict[str, _ArchetypePolicy] = {
    "Cycle": _ArchetypePolicy(
        play_style="Быстрый цикл",
        required_soft_checks=frozenset({
            "big_spell", "small_spell", "air_defense", "anti_tank", "anti_swarm", "cycle",
        }),
        min_air_defense=1,
        require_building=False,
        min_cycle_cards=2,
        required_role_ids=frozenset({
            "win_condition", "big_spell", "small_spell", "anti_air", "dps", "splash",
        }),
        attack_bias=0.65,
    ),
    "Log Bait": _ArchetypePolicy(
        play_style="Сплит-пуш",
        required_soft_checks=frozenset({
            "big_spell", "small_spell", "air_defense", "anti_swarm",
        }),
        min_air_defense=1,
        require_building=False,
        min_cycle_cards=1,
        required_role_ids=frozenset({
            "win_condition", "big_spell", "small_spell", "anti_air", "splash", "dps",
        }),
        attack_bias=0.6,
    ),
    "Fireball Bait": _ArchetypePolicy(
        play_style="Сплит-пуш",
        required_soft_checks=frozenset({
            "big_spell", "small_spell", "air_defense", "anti_swarm",
        }),
        min_air_defense=1,
        require_building=False,
        min_cycle_cards=1,
        required_role_ids=frozenset({
            "win_condition", "big_spell", "small_spell", "anti_air", "splash",
        }),
        attack_bias=0.6,
    ),
    "Beatdown": _ArchetypePolicy(
        play_style="Контрпуш",
        required_soft_checks=frozenset({
            "big_spell", "small_spell", "air_defense", "anti_swarm",
        }),
        min_air_defense=1,
        require_building=False,
        min_cycle_cards=0,
        required_role_ids=frozenset({
            "win_condition", "big_spell", "small_spell", "tank", "anti_air", "splash",
        }),
        attack_bias=0.7,
    ),
    "Lava": _ArchetypePolicy(
        play_style="Контрпуш",
        required_soft_checks=frozenset({
            "big_spell", "small_spell", "anti_swarm", "anti_tank",
        }),
        min_air_defense=0,
        require_building=False,
        min_cycle_cards=0,
        required_role_ids=frozenset({
            "win_condition", "big_spell", "small_spell", "splash", "dps",
        }),
        attack_bias=0.7,
    ),
    "Bridge Spam": _ArchetypePolicy(
        play_style="Агрессивная",
        required_soft_checks=frozenset({
            "small_spell", "air_defense", "anti_swarm", "anti_tank",
        }),
        min_air_defense=1,
        require_building=False,
        min_cycle_cards=0,
        required_role_ids=frozenset({
            "win_condition", "small_spell", "mini_tank", "anti_air", "splash", "dps",
        }),
        attack_bias=0.75,
    ),
    "Siege": _ArchetypePolicy(
        play_style="Осадная",
        required_soft_checks=frozenset({
            "big_spell", "small_spell", "air_defense", "building", "anti_swarm",
        }),
        min_air_defense=1,
        require_building=True,
        min_cycle_cards=1,
        required_role_ids=frozenset({
            "win_condition", "big_spell", "small_spell", "building", "anti_air", "splash",
        }),
        attack_bias=0.45,
    ),
    "Control": _ArchetypePolicy(
        play_style="Контроль",
        required_soft_checks=frozenset({
            "big_spell", "small_spell", "air_defense", "building", "anti_swarm",
        }),
        min_air_defense=1,
        require_building=True,
        min_cycle_cards=1,
        required_role_ids=frozenset({
            "win_condition", "big_spell", "small_spell", "building", "anti_air", "splash",
        }),
        attack_bias=0.4,
    ),
    "Graveyard": _ArchetypePolicy(
        play_style="Контроль",
        required_soft_checks=frozenset({
            "big_spell", "small_spell", "air_defense", "anti_swarm", "anti_tank",
        }),
        min_air_defense=1,
        require_building=False,
        min_cycle_cards=0,
        required_role_ids=frozenset({
            "win_condition", "big_spell", "small_spell", "anti_air", "splash", "mini_tank",
        }),
        attack_bias=0.5,
    ),
    "Royal Giant": _ArchetypePolicy(
        play_style="Оборонительная",
        required_soft_checks=frozenset({
            "big_spell", "small_spell", "air_defense", "anti_swarm", "anti_tank",
        }),
        min_air_defense=1,
        require_building=False,
        min_cycle_cards=0,
        required_role_ids=frozenset({
            "win_condition", "big_spell", "small_spell", "anti_air", "splash", "dps",
        }),
        attack_bias=0.55,
    ),
    "Split Lane": _ArchetypePolicy(
        play_style="Сплит-пуш",
        required_soft_checks=frozenset({
            "small_spell", "air_defense", "anti_swarm", "cycle",
        }),
        min_air_defense=1,
        require_building=False,
        min_cycle_cards=2,
        required_role_ids=frozenset({
            "win_condition", "small_spell", "anti_air", "splash", "dps",
        }),
        attack_bias=0.65,
    ),
}

_DEFAULT_POLICY = _ArchetypePolicy(
    play_style="Гибридная",
    required_soft_checks=frozenset({
        "big_spell", "small_spell", "air_defense", "anti_tank", "anti_swarm",
    }),
    min_air_defense=1,
    require_building=False,
    min_cycle_cards=0,
    required_role_ids=frozenset({
        "win_condition", "big_spell", "small_spell", "anti_air", "splash", "dps",
    }),
    attack_bias=0.55,
)


def detect_primary_win(cards: list[str]) -> str | None:
    """Главная угроза: сначала Primary WC, иначе Secondary Pressure / role."""
    primaries = [c for c in cards if is_primary_win_condition(c)]
    if primaries:
        # Предпочитаем более «классическую» угрозу: дешевле обычно = cycle win.
        return sorted(primaries, key=lambda c: (get_card_profile(c).elixir, c))[0]

    secondaries = [c for c in cards if is_secondary_pressure(c) or c in WIN_CONDITIONS]
    if secondaries:
        return sorted(secondaries, key=lambda c: (get_card_profile(c).elixir, c))[0]

    for c in cards:
        if get_card_profile(c).is_win_condition and not is_tower_threat(c):
            return c
    return None


def infer_deck_intent(
    cards: list[str],
    *,
    archetype: str | None = None,
) -> DeckIntent:
    """Построить DeckIntent для колоды.

    ``archetype`` если уже известен (passport/builder); иначе лёгкий fallback Meta.
    """
    arch = archetype or "Meta"
    policy = _POLICIES.get(arch, _DEFAULT_POLICY)
    primary = detect_primary_win(cards)

    required = set(policy.required_soft_checks)
    if policy.require_building:
        required.add("building")
    if policy.min_cycle_cards > 0:
        required.add("cycle")
    if policy.min_air_defense > 0:
        required.add("air_defense")

    return DeckIntent(
        archetype=arch,
        play_style=policy.play_style,
        primary_win=primary,
        required_soft_checks=frozenset(required),
        min_air_defense=policy.min_air_defense,
        require_building=policy.require_building,
        min_cycle_cards=policy.min_cycle_cards,
        required_role_ids=policy.required_role_ids,
        attack_bias=policy.attack_bias,
    )


class DeckIntentEngine:
    """Фасад для анализа / soft-balance."""

    @staticmethod
    def infer(cards: list[str], *, archetype: str | None = None) -> DeckIntent:
        return infer_deck_intent(cards, archetype=archetype)
