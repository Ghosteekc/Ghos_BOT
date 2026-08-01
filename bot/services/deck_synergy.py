"""Многоуровневая оценка внутренней синергии колоды.

Не среднее по всем парам: топ core-связок + роли + gameplan − конфликты.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.services.card_data import (
    WIN_CONDITIONS,
    card_has_role,
    get_card_elixir,
    is_building,
    is_pure_spell,
)
from bot.services.card_matchups import ru, synergy_between
from bot.services.deck_builder.archetype_detect import detect_archetype_from_cards
from bot.services.deck_builder.constants import (
    ARCHETYPE_ANCHORS,
    ARCHETYPE_PRIMARY_WIN,
    KNOWN_SYNERGY_PAIRS,
    SYNERGY_PARTIAL,
    SYNERGY_STRONG,
)

# Доп. базовые CR-связки поверх KNOWN_SYNERGY_PAIRS.
_CORE_EXTRA: dict[frozenset[str], int] = {
    frozenset({"Bowler", "Tornado"}): 95,
    frozenset({"Ice Wizard", "Tornado"}): 94,
    frozenset({"Executioner", "Tornado"}): 96,
    frozenset({"Magic Archer", "Tornado"}): 96,
    frozenset({"Hog Rider", "Earthquake"}): 93,
    frozenset({"Hog Rider", "Fireball"}): 88,
    frozenset({"Hog Rider", "The Log"}): 86,
    frozenset({"Lumberjack", "Balloon"}): 96,
    frozenset({"Balloon", "Freeze"}): 90,
    frozenset({"Goblin Barrel", "Princess"}): 99,
    frozenset({"Goblin Barrel", "Goblin Gang"}): 90,
    frozenset({"Miner", "Poison"}): 92,
    frozenset({"Graveyard", "Poison"}): 94,
    frozenset({"Graveyard", "Freeze"}): 91,
    frozenset({"X-Bow", "Tesla"}): 93,
    frozenset({"Mortar", "Knight"}): 88,
    frozenset({"Royal Giant", "Fisherman"}): 91,
    frozenset({"Royal Hogs", "Earthquake"}): 89,
    frozenset({"Battle Ram", "P.E.K.K.A"}): 92,
    frozenset({"Bandit", "Royal Ghost"}): 90,
    frozenset({"Golem", "Lightning"}): 88,
    frozenset({"Golem", "Baby Dragon"}): 90,
    frozenset({"Lava Hound", "Balloon"}): 97,
    frozenset({"Sparky", "Giant"}): 87,
    frozenset({"Three Musketeers", "Elixir Collector"}): 90,
}

_HEAVY_WINS = frozenset({
    "Golem", "Lava Hound", "Electro Giant", "Elixir Golem", "Goblin Giant",
    "Giant", "P.E.K.K.A", "Royal Giant", "Sparky",
})
_BRIDGE_WINS = frozenset({
    "Hog Rider", "Battle Ram", "Ram Rider", "Royal Hogs", "Wall Breakers",
    "Elite Barbarians", "Goblin Barrel", "Skeleton Barrel", "Goblin Drill",
})
_SIEGE = frozenset({"X-Bow", "Mortar"})
_CYCLE_CARDS = frozenset({
    "Skeletons", "Ice Spirit", "Electro Spirit", "Fire Spirit", "Heal Spirit",
    "Goblins", "Spear Goblins", "Bats", "Ice Golem",
})
_CHEAP_SPELLS = frozenset({
    "The Log", "Zap", "Arrows", "Giant Snowball", "Barbarian Barrel", "Royal Delivery",
})
_RANGED_SUPPORT = frozenset({
    "Musketeer", "Archers", "Dart Goblin", "Firecracker", "Magic Archer",
    "Flying Machine", "Wizard", "Electro Wizard", "Ice Wizard", "Executioner",
    "Hunter", "Little Prince", "Princess", "Mega Minion",
})
_MINI_TANKS = frozenset({
    "Knight", "Valkyrie", "Ice Golem", "Dark Prince", "Battle Healer", "Golden Knight",
})


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _wins(deck: list[str]) -> list[str]:
    return [c for c in deck if c in WIN_CONDITIONS or card_has_role(c, "win_condition")]


def _core_pair_table() -> dict[frozenset[str], int]:
    table = dict(KNOWN_SYNERGY_PAIRS)
    table.update(_CORE_EXTRA)
    return table


def _pair_strength(a: str, b: str, known: dict[frozenset[str], int]) -> int:
    key = frozenset({a, b})
    if key in known:
        return known[key]
    tier = synergy_between(a, b) or synergy_between(b, a)
    if tier == "strong":
        return SYNERGY_STRONG
    if tier == "partial":
        return SYNERGY_PARTIAL
    return 0


@dataclass
class DeckSynergyBreakdown:
    core: float = 0.0
    role: float = 0.0
    game_plan: float = 0.0
    conflict: float = 0.0


@dataclass
class DeckSynergyEvaluation:
    score: float = 50.0
    notes: list[str] = field(default_factory=list)
    breakdown: DeckSynergyBreakdown = field(default_factory=DeckSynergyBreakdown)

    @classmethod
    def evaluate(cls, cards: list[str]) -> DeckSynergyEvaluation:
        unique = list(dict.fromkeys(cards))
        if len(unique) < 2:
            return cls(score=50.0)

        known = _core_pair_table()
        core_pts, core_notes = _score_core(unique, known)
        role_pts, role_notes = _score_roles(unique)
        plan_pts, plan_notes = _score_game_plan(unique)
        conflict_pts, conflict_notes = _score_conflicts(unique)

        raw = 40.0 + core_pts + role_pts + plan_pts + conflict_pts
        score = round(_clamp(raw), 1)

        notes: list[str] = []
        for bucket in (core_notes, role_notes, plan_notes, conflict_notes):
            for line in bucket:
                if line not in notes:
                    notes.append(line)
                if len(notes) >= 6:
                    break
            if len(notes) >= 6:
                break

        return cls(
            score=score,
            notes=notes,
            breakdown=DeckSynergyBreakdown(
                core=round(core_pts, 1),
                role=round(role_pts, 1),
                game_plan=round(plan_pts, 1),
                conflict=round(conflict_pts, 1),
            ),
        )


def _score_core(
    cards: list[str],
    known: dict[frozenset[str], int],
) -> tuple[float, list[str]]:
    """Топ-N core-связок → до +35. Не размываем нулевыми парами."""
    scored: list[tuple[int, str, str]] = []
    for i, a in enumerate(cards):
        for b in cards[i + 1 :]:
            strength = _pair_strength(a, b, known)
            if strength >= SYNERGY_PARTIAL:
                scored.append((strength, a, b))
    scored.sort(key=lambda x: -x[0])
    top = scored[:4]
    if not top:
        return 0.0, []

    # Веса: лучшая связка доминирует.
    weights = (1.0, 0.55, 0.35, 0.25)
    weighted = 0.0
    weight_sum = 0.0
    notes: list[str] = []
    for idx, (strength, a, b) in enumerate(top):
        w = weights[idx]
        weighted += (strength / 100.0) * w
        weight_sum += w
        left, right = sorted((a, b))
        notes.append(f"{ru(left)} + {ru(right)}")

    quality = weighted / weight_sum if weight_sum else 0.0
    # 1 сильная связка ≈ +28…35; несколько топ-пар слегка усиливают.
    bonus = min(4.0, max(0.0, (len(top) - 1) * 1.5))
    points = quality * 31.0 + bonus
    return min(35.0, points), notes[:4]


def _has(cards: list[str], pred) -> bool:
    return any(pred(c) for c in cards)


def _score_roles(cards: list[str]) -> tuple[float, list[str]]:
    """Взаимное усиление ролей → до +20."""
    points = 0.0
    notes: list[str] = []
    present = set(cards)

    has_tank = _has(cards, lambda c: card_has_role(c, "tank") or c in _HEAVY_WINS)
    has_splash = _has(cards, lambda c: card_has_role(c, "splash") or card_has_role(c, "anti_swarm"))
    has_building = _has(cards, lambda c: is_building(c) or card_has_role(c, "building"))
    has_cycle = any(c in _CYCLE_CARDS or get_card_elixir(c) <= 2 for c in cards)
    has_mini = any(c in _MINI_TANKS or card_has_role(c, "mini_tank") for c in cards)
    has_ranged = any(c in _RANGED_SUPPORT for c in cards)
    has_cheap_spell = any(c in _CHEAP_SPELLS or card_has_role(c, "small_spell") for c in cards)
    has_big_spell = _has(cards, lambda c: card_has_role(c, "big_spell") or (
        is_pure_spell(c) and get_card_elixir(c) >= 4
    ))

    if has_tank and has_splash:
        points += 5.0
        notes.append("Танк + сплеш усиливают набор и зачистку")
    if has_building and has_cycle:
        points += 4.0
        notes.append("Здание + цикл ускоряют оборону и контрпуш")
    if has_mini and has_ranged:
        points += 4.5
        notes.append("Мини-танк + дальний саппорт")
    if has_cycle and has_cheap_spell:
        points += 3.5
        notes.append("Быстрый цикл + дешёвый спелл")
    if has_big_spell and (_wins(cards) or has_building):
        points += 3.0
        notes.append("Большой спелл поддерживает win-condition / здание")

    # Tornado + splash DPS — классическая control-роль
    if "Tornado" in present and any(
        c in present for c in ("Executioner", "Wizard", "Bowler", "Baby Dragon", "Magic Archer", "Ice Wizard")
    ):
        points += 4.0
        if not any("Торнадо" in n or "Tornado" in n for n in notes):
            notes.append("Торнадо усиливает сплеш-защиту")

    return min(20.0, points), notes[:3]


def _score_game_plan(cards: list[str]) -> tuple[float, list[str]]:
    """Согласованность с одной стратегией → до +25."""
    arch = detect_archetype_from_cards(cards)
    anchors = ARCHETYPE_ANCHORS.get(arch, set())
    primary = ARCHETYPE_PRIMARY_WIN.get(arch, [])
    present = set(cards)
    notes: list[str] = []

    hit_anchors = len(anchors & present)
    has_primary = any(c in present for c in primary) if primary else bool(_wins(cards))

    points = 0.0
    if has_primary:
        points += 10.0
    if hit_anchors >= 2:
        points += 10.0
        notes.append(f"Карты работают на план {arch}")
    elif hit_anchors == 1:
        points += 5.0
        notes.append(f"Есть якорь архетипа {arch}")
    elif arch != "Meta" and has_primary:
        points += 4.0
        notes.append(f"Единый план: {arch}")

    # Цикл Hog: дешёвые карты + Hog + малый спелл
    if "Hog Rider" in present:
        cycle_n = sum(1 for c in cards if get_card_elixir(c) <= 2)
        if cycle_n >= 3 and any(c in _CHEAP_SPELLS for c in present):
            points += 5.0
            notes.append("Цикл Хога согласован по темпу")

    # LavaLoon
    if {"Lava Hound", "Balloon"} <= present:
        points += 6.0
        notes.append("Lava + Balloon — единый воздушный план")

    # Bait
    if "Goblin Barrel" in present and any(
        c in present for c in ("Princess", "Goblin Gang", "Dart Goblin", "Skeleton Barrel")
    ):
        points += 5.0
        notes.append("Bait-угрозы связаны одной стратегией")

    return min(25.0, points), notes[:3]


def _score_conflicts(cards: list[str]) -> tuple[float, list[str]]:
    """Антиконфликты → 0…−30."""
    wins = _wins(cards)
    notes: list[str] = []
    penalty = 0.0
    present = set(cards)

    heavy = [c for c in wins if c in _HEAVY_WINS]
    bridge = [c for c in wins if c in _BRIDGE_WINS]
    siege = [c for c in wins if c in _SIEGE]

    # Две тяжёлые WC без общего beatdown-плана
    if len(heavy) >= 2:
        arch = detect_archetype_from_cards(cards)
        if arch not in {"Beatdown", "Lava", "Bridge Spam"}:
            penalty += 14.0
            notes.append("Две тяжёлые win-condition без общей стратегии")
        else:
            penalty += 6.0
            notes.append("Две тяжёлые win-condition перегружают эликсир")

    # Beatdown WC + siege
    if heavy and siege:
        penalty += 12.0
        notes.append("Осада конфликтует с тяжёлым танком")

    # Bridge spam + slow beatdown tank without bridge tools
    if any(c in present for c in ("Golem", "Lava Hound", "Electro Giant")) and bridge:
        if not any(c in present for c in ("Battle Ram", "Ram Rider", "Bandit")):
            penalty += 8.0
            notes.append("Тяжёлый танк и bridge-WC тянут колоду в разные планы")

    # Две дорогие win без дешёвого цикла (только для полной колоды).
    if len(cards) >= 6:
        avg = sum(get_card_elixir(c) for c in cards) / len(cards)
        if len(wins) >= 2 and avg >= 4.2:
            penalty += 6.0
            notes.append("Тяжёлый состав при нескольких win-condition")

    return -min(30.0, penalty), notes[:3]


def evaluate_deck_synergy(cards: list[str]) -> DeckSynergyEvaluation:
    return DeckSynergyEvaluation.evaluate(cards)
