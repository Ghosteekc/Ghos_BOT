"""WinPlanCheck — обязательная проверка понятного способа выигрывать после Builder.

Колода, которая закрывает роли, но не умеет выигрывать матч, не считается готовой.
При пробелах Builder заменяет filler-карты, пока план победы не станет цельным.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from bot.services.card_data import (
    WIN_CONDITIONS,
    card_has_role,
    get_card_elixir,
    spell_counter_tier_vs_building,
)
from bot.services.deck_builder.constants import (
    ARCHETYPE_PRIMARY_WIN,
    MAX_SPELLS,
    MAX_WINS,
    ROLE_BIG_SPELL,
    ROLE_COUNTERPUSH,
    ROLE_CYCLE,
    ROLE_DPS,
    ROLE_MINI_TANK,
    ROLE_SUPPORT,
    ROLE_TANK,
    ROLE_WIN,
)
from bot.services.deck_builder.loader import DeckDatabase
from bot.services.deck_intent import DeckIntent, DeckIntentEngine
from bot.services.special_card_policy import SpecialCardPolicy

PairSynergyFn = Callable[[str, str], int]

# Добивание башни / закрытие партии.
_FINISHERS = frozenset({
    "Fireball", "Rocket", "Lightning", "Poison", "Earthquake",
})

# Win / юниты, которые сами обходят или ломают здания.
_BUILDING_BREAK_WINS = frozenset({
    "Hog Rider", "Miner", "Goblin Barrel", "Goblin Drill", "Wall Breakers",
    "Skeleton Barrel", "Royal Hogs", "Balloon", "Royal Giant", "X-Bow", "Mortar",
    "Ram Rider", "Battle Ram", "Mighty Miner",
})

_MAX_WIN_PLAN_SWAPS = 5

# Приоритет закрытия пробелов Win Plan.
_GAP_ORDER = (
    "primary_win",
    "finishing_power",
    "secondary_threat",
    "building_break",
    "constant_pressure",
    "counterattack",
)


@dataclass(frozen=True)
class WinPlanCheck:
    """Срез способности колоды выигрывать матч."""

    primary_win: bool
    secondary_threat: bool
    constant_pressure: bool
    finishing_power: bool
    building_break: bool
    counterattack: bool
    primary_card: str | None = None

    @property
    def complete(self) -> bool:
        return (
            self.primary_win
            and self.secondary_threat
            and self.constant_pressure
            and self.finishing_power
            and self.building_break
            and self.counterattack
        )

    def missing(self) -> list[str]:
        flags = (
            ("primary_win", self.primary_win),
            ("secondary_threat", self.secondary_threat),
            ("constant_pressure", self.constant_pressure),
            ("finishing_power", self.finishing_power),
            ("building_break", self.building_break),
            ("counterattack", self.counterattack),
        )
        return [name for name, ok in flags if not ok]


def _is_attack_win(name: str) -> bool:
    return name in WIN_CONDITIONS


def _is_spell(db: DeckDatabase, name: str) -> bool:
    del db
    return card_has_role(name, "spell")


def _primary_card(deck: list[str], intent: DeckIntent) -> str | None:
    if intent.primary_win and intent.primary_win in deck:
        return intent.primary_win
    wins = [c for c in deck if _is_attack_win(c)]
    return wins[0] if wins else None


def _is_cycleish(card: str) -> bool:
    return card_has_role(card, ROLE_CYCLE) or get_card_elixir(card) <= 2


def _is_secondary_threat(card: str, primary: str | None) -> bool:
    if card == primary:
        return False
    if card in _FINISHERS or card_has_role(card, ROLE_BIG_SPELL):
        return True
    if card_has_role(card, ROLE_WIN) and not _is_attack_win(card):
        return True
    if card_has_role(card, ROLE_COUNTERPUSH):
        return True
    if card_has_role(card, ROLE_DPS) or card_has_role(card, ROLE_MINI_TANK):
        return get_card_elixir(card) >= 3 or card_has_role(card, ROLE_COUNTERPUSH)
    if card_has_role(card, ROLE_SUPPORT) and get_card_elixir(card) >= 4:
        return True
    if card_has_role(card, ROLE_TANK) and card != primary:
        return True
    return False


def _has_finishing(deck: list[str]) -> bool:
    if any(c in _FINISHERS or card_has_role(c, ROLE_BIG_SPELL) for c in deck):
        return True
    # Осада сама добивает башню при контроле.
    return any(c in {"X-Bow", "Mortar"} for c in deck)


def _has_building_break(deck: list[str], primary: str | None) -> bool:
    if primary and primary in _BUILDING_BREAK_WINS:
        return True
    for c in deck:
        if spell_counter_tier_vs_building(c) is not None:
            return True
        # Тяжёлый танк / PEKKA продавливает здания под саппортом.
        if card_has_role(c, ROLE_TANK) and get_card_elixir(c) >= 5:
            return True
        if c in {"P.E.K.K.A", "Electro Giant", "Goblin Giant", "Golem", "Giant"}:
            return True
    return False


def _has_constant_pressure(deck: list[str], intent: DeckIntent, primary: str | None) -> bool:
    cycle_n = sum(1 for c in deck if _is_cycleish(c))
    if cycle_n >= max(2, intent.min_cycle_cards or 0):
        return True
    if cycle_n >= 2:
        return True
    # Beatdown / tank push — постоянное давление набора.
    if any(card_has_role(c, ROLE_TANK) for c in deck) and any(
        card_has_role(c, ROLE_SUPPORT) or card_has_role(c, ROLE_DPS) for c in deck
    ):
        return True
    threats = sum(1 for c in deck if _is_secondary_threat(c, primary) or c == primary)
    if threats >= 2 and any(card_has_role(c, ROLE_COUNTERPUSH) for c in deck):
        return True
    if primary in {"X-Bow", "Mortar", "Royal Giant", "Goblin Barrel"}:
        return True
    return False


def _has_counterattack(deck: list[str], intent: DeckIntent, primary: str | None) -> bool:
    if any(card_has_role(c, ROLE_COUNTERPUSH) for c in deck):
        return True
    # Дешёвый win + цикл = контратака после обмена.
    if primary and sum(1 for c in deck if _is_cycleish(c)) >= 2:
        return True
    # Остатки защиты → пуш: mini-tank / tank рядом с win.
    if primary and any(
        card_has_role(c, ROLE_MINI_TANK) or (
            card_has_role(c, ROLE_TANK) and c != primary
        )
        for c in deck
    ):
        return True
    if intent.attack_bias >= 0.6 and any(card_has_role(c, ROLE_DPS) for c in deck):
        return True
    return False


def evaluate_win_plan(
    deck: list[str],
    db: DeckDatabase,
    archetype: str,
    *,
    intent: DeckIntent | None = None,
) -> WinPlanCheck:
    """Проверка 6 пунктов Win Plan на готовой колоде."""
    del db  # роли читаем через card_has_role / profiles
    intent = intent or DeckIntentEngine.infer(deck, archetype=archetype)
    primary = _primary_card(deck, intent)
    return WinPlanCheck(
        primary_win=primary is not None,
        secondary_threat=any(_is_secondary_threat(c, primary) for c in deck),
        constant_pressure=_has_constant_pressure(deck, intent, primary),
        finishing_power=_has_finishing(deck),
        building_break=_has_building_break(deck, primary),
        counterattack=_has_counterattack(deck, intent, primary),
        primary_card=primary,
    )


def _candidate_matches_gap(card: str, gap: str, archetype: str) -> bool:
    if gap == "primary_win":
        del archetype
        return _is_attack_win(card)
    if gap == "secondary_threat":
        return _is_secondary_threat(card, primary=None)
    if gap == "constant_pressure":
        return _is_cycleish(card) or card_has_role(card, ROLE_COUNTERPUSH)
    if gap == "finishing_power":
        return card in _FINISHERS or card_has_role(card, ROLE_BIG_SPELL)
    if gap == "building_break":
        if spell_counter_tier_vs_building(card) is not None:
            return True
        if card in _BUILDING_BREAK_WINS:
            return True
        if card in {"P.E.K.K.A", "Electro Giant", "Goblin Giant", "Golem", "Giant"}:
            return True
        return card_has_role(card, ROLE_TANK) and get_card_elixir(card) >= 5
    if gap == "counterattack":
        return (
            card_has_role(card, ROLE_COUNTERPUSH)
            or card_has_role(card, ROLE_MINI_TANK)
            or card_has_role(card, ROLE_DPS)
            or _is_cycleish(card)
        )
    return False


def _pick_win_plan_fix(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
    gap: str,
    pair_synergy: PairSynergyFn,
) -> str | None:
    """Лучший кандидат из pool, закрывающий конкретный пробел Win Plan."""
    from bot.services.deck_builder.balance import count_spells, count_wins, is_spell

    context = list(dict.fromkeys([*deck, *core]))
    candidates = [
        c for c in pool
        if c not in deck
        and _candidate_matches_gap(c, gap, archetype)
        and not SpecialCardPolicy.forbid_as_auto_pick(c, deck=context, archetype=archetype)
    ]
    if not candidates:
        # primary_win: любой attack win, если предпочтения архетипа пусты
        if gap == "primary_win":
            candidates = [
                c for c in pool
                if c not in deck and _is_attack_win(c) and not is_spell(db, c)
            ]
        else:
            return None

    spell_n = count_spells(deck, db)
    win_n = count_wins(deck, db)

    def legal(card: str) -> bool:
        if is_spell(db, card) and spell_n >= MAX_SPELLS:
            return False
        if _is_attack_win(card) and win_n >= MAX_WINS and gap != "primary_win":
            return False
        if gap == "primary_win" and _is_attack_win(card) and win_n >= MAX_WINS:
            # замена filler'ом-win допустима только если wins уже 0
            return win_n == 0
        return True

    candidates = [c for c in candidates if legal(c)]
    if not candidates:
        return None

    return max(
        candidates,
        key=lambda c: (
            sum(pair_synergy(c, x) for x in core) * 3
            + sum(pair_synergy(c, x) for x in deck)
            + (20 if c in ARCHETYPE_PRIMARY_WIN.get(archetype, []) else 0)
            + (15 if c in _FINISHERS else 0)
            + (12 if spell_counter_tier_vs_building(c) == "strong" else 0)
        ),
    )


def enforce_win_plan(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
    pair_synergy: PairSynergyFn,
    *,
    max_swaps: int = _MAX_WIN_PLAN_SWAPS,
) -> list[str]:
    """Заменяет weakest fillers, пока Win Plan не станет complete (или лимит свапов)."""
    from bot.services.deck_builder.balance import _replace_weakest_filler

    out = list(deck)
    if len(out) != 8:
        return out

    for _ in range(max_swaps):
        check = evaluate_win_plan(out, db, archetype)
        if check.complete:
            return out

        missing = check.missing()
        # Закрываем пробелы в фиксированном порядке важности.
        gap = next((g for g in _GAP_ORDER if g in missing), missing[0])
        pick = _pick_win_plan_fix(out, core, db, pool, archetype, gap, pair_synergy)
        if not pick:
            # Пробуем следующий пробел, если для текущего нет кандидата.
            fixed = False
            for alt in missing:
                if alt == gap:
                    continue
                pick = _pick_win_plan_fix(out, core, db, pool, archetype, alt, pair_synergy)
                if pick:
                    gap = alt
                    fixed = True
                    break
            if not fixed or not pick:
                break

        nxt = _replace_weakest_filler(out, core, pick, pair_synergy)
        if nxt == out:
            break
        out = nxt

    return out[:8]
