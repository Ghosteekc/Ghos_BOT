"""Определение архетипа колоды по нескольким признакам.

Не меняет публичный API ``_detect_archetype`` / ``detectArchetype`` —
только внутреннюю логику выбора наиболее вероятного архетипа.

Учитывает одновременно:
  win condition, средний эликсир, support, цикл, заклинания, здания,
  стиль защиты и стиль атаки (+ якоря архетипа из констант проекта).
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.services.card_data import WIN_CONDITIONS, card_has_role, get_card_elixir
from bot.services.deck_builder.constants import (
    ARCHETYPE_ANCHORS,
    ARCHETYPE_ELIXIR,
    ARCHETYPE_PRIMARY_WIN,
    ARCHETYPES,
    DEFAULT_ELIXIR_MAX,
    DEFAULT_ELIXIR_MIN,
    ROLE_AIR,
    ROLE_BIG_SPELL,
    ROLE_BUILDING,
    ROLE_COUNTERPUSH,
    ROLE_CYCLE,
    ROLE_DEFENSIVE,
    ROLE_DPS,
    ROLE_MINI_TANK,
    ROLE_SMALL_SPELL,
    ROLE_SPLASH,
    ROLE_SUPPORT,
    ROLE_TANK,
)

# Веса осей (сумма = 1.0).
_W_WIN = 0.26
_W_ELIXIR = 0.14
_W_ANCHORS = 0.14
_W_CYCLE = 0.10
_W_SUPPORT = 0.08
_W_SPELLS = 0.08
_W_BUILDINGS = 0.08
_W_DEFENSE = 0.06
_W_ATTACK = 0.06

# Ожидания по стилю (на основе существующих политик / мета-диапазонов).
# Не новые роли — только пороги для скоринга.
_ARCHETYPE_STYLE: dict[str, dict[str, float | int | str]] = {
    "Cycle": {
        "min_cycle": 2,
        "building_want": 0.25,
        "attack": "pressure",
        "defense": "cheap",
        "support_want": 1,
    },
    "Log Bait": {
        "min_cycle": 1,
        "building_want": 0.2,
        "attack": "bait",
        "defense": "swarm",
        "support_want": 1,
    },
    "Fireball Bait": {
        "min_cycle": 1,
        "building_want": 0.2,
        "attack": "bait",
        "defense": "swarm",
        "support_want": 1,
    },
    "Beatdown": {
        "min_cycle": 0,
        "building_want": 0.15,
        "attack": "tank_push",
        "defense": "counter",
        "support_want": 2,
    },
    "Lava": {
        "min_cycle": 0,
        "building_want": 0.1,
        "attack": "air_push",
        "defense": "ground",
        "support_want": 2,
    },
    "Bridge Spam": {
        "min_cycle": 0,
        "building_want": 0.15,
        "attack": "bridge",
        "defense": "reactive",
        "support_want": 2,
    },
    "Siege": {
        "min_cycle": 1,
        "building_want": 1.0,
        "attack": "siege",
        "defense": "building",
        "support_want": 1,
    },
    "Control": {
        "min_cycle": 1,
        "building_want": 0.7,
        "attack": "chip",
        "defense": "building",
        "support_want": 1,
    },
    "Graveyard": {
        "min_cycle": 0,
        "building_want": 0.35,
        "attack": "spell_bait",
        "defense": "tanky",
        "support_want": 2,
    },
    "Royal Giant": {
        "min_cycle": 0,
        "building_want": 0.35,
        "attack": "rg",
        "defense": "building",
        "support_want": 2,
    },
    "Split Lane": {
        "min_cycle": 2,
        "building_want": 0.2,
        "attack": "split",
        "defense": "cheap",
        "support_want": 1,
    },
    "Meta": {
        "min_cycle": 0,
        "building_want": 0.3,
        "attack": "hybrid",
        "defense": "hybrid",
        "support_want": 1,
    },
}

_BAIT_MARKERS = frozenset({
    "Princess", "Goblin Gang", "Dart Goblin", "Goblin Barrel", "Skeleton Barrel",
    "Firecracker", "Wall Breakers",
})
_BRIDGE_MARKERS = frozenset({
    "Bandit", "Royal Ghost", "Battle Ram", "Ram Rider", "Dark Prince",
    "Elite Barbarians", "Boss Bandit",
})
_SIEGE_MARKERS = frozenset({"X-Bow", "Mortar", "Tesla", "Cannon", "Inferno Tower"})
_TANK_MARKERS = frozenset({
    "Golem", "Electro Giant", "Giant", "Elixir Golem", "Lava Hound", "Goblin Giant",
})


@dataclass(frozen=True)
class _DeckSignals:
    cards: frozenset[str]
    avg_elixir: float
    wins: tuple[str, ...]
    primary_win: str | None
    cycle_n: int
    building_n: int
    spell_n: int
    big_spell: bool
    small_spell: bool
    support_n: int
    tank_n: int
    mini_tank_n: int
    defensive_n: int
    counterpush_n: int
    splash_n: int
    air_n: int
    dps_n: int


def _count_role(cards: list[str], role: str) -> int:
    return sum(1 for c in cards if card_has_role(c, role))


def _extract_signals(cards: list[str]) -> _DeckSignals:
    if not cards:
        return _DeckSignals(
            cards=frozenset(),
            avg_elixir=4.0,
            wins=(),
            primary_win=None,
            cycle_n=0,
            building_n=0,
            spell_n=0,
            big_spell=False,
            small_spell=False,
            support_n=0,
            tank_n=0,
            mini_tank_n=0,
            defensive_n=0,
            counterpush_n=0,
            splash_n=0,
            air_n=0,
            dps_n=0,
        )

    elixirs = [get_card_elixir(c) for c in cards]
    avg = sum(elixirs) / len(elixirs)
    wins = tuple(c for c in cards if c in WIN_CONDITIONS or card_has_role(c, "win_condition"))
    primary = next((c for c in wins if c in WIN_CONDITIONS), wins[0] if wins else None)
    cycle_n = sum(
        1 for c in cards
        if card_has_role(c, ROLE_CYCLE) or get_card_elixir(c) <= 2
    )

    return _DeckSignals(
        cards=frozenset(cards),
        avg_elixir=round(avg, 2),
        wins=wins,
        primary_win=primary,
        cycle_n=cycle_n,
        building_n=_count_role(cards, ROLE_BUILDING),
        spell_n=_count_role(cards, "spell"),
        big_spell=any(card_has_role(c, ROLE_BIG_SPELL) for c in cards),
        small_spell=any(card_has_role(c, ROLE_SMALL_SPELL) for c in cards),
        support_n=_count_role(cards, ROLE_SUPPORT) + _count_role(cards, ROLE_DPS),
        tank_n=_count_role(cards, ROLE_TANK),
        mini_tank_n=_count_role(cards, ROLE_MINI_TANK),
        defensive_n=_count_role(cards, ROLE_DEFENSIVE),
        counterpush_n=_count_role(cards, ROLE_COUNTERPUSH),
        splash_n=_count_role(cards, ROLE_SPLASH),
        air_n=_count_role(cards, ROLE_AIR),
        dps_n=_count_role(cards, ROLE_DPS),
    )


def _score_win(sig: _DeckSignals, archetype: str) -> float:
    primary_list = ARCHETYPE_PRIMARY_WIN.get(archetype, [])
    if not primary_list and archetype not in ARCHETYPE_ANCHORS:
        return 40.0

    hits = [w for w in sig.wins if w in primary_list]
    if hits:
        # Основной win архетипа в колоде
        score = 100.0 if sig.primary_win in primary_list else 82.0
        return score

    # Частичный сигнал по якорям-win
    anchors = ARCHETYPE_ANCHORS.get(archetype, set())
    if sig.cards & anchors & WIN_CONDITIONS:
        return 55.0

    # Спец-кейсы без жёсткого early-return по первой карте
    if archetype == "Lava" and ("Lava Hound" in sig.cards or "Balloon" in sig.cards):
        return 70.0 if {"Lava Hound", "Balloon"} <= sig.cards else 48.0
    if archetype == "Bridge Spam" and sig.cards & _BRIDGE_MARKERS:
        return 50.0
    if archetype == "Beatdown" and sig.cards & _TANK_MARKERS:
        return 45.0
    if archetype == "Siege" and sig.cards & {"X-Bow", "Mortar"}:
        return 75.0
    if archetype == "Log Bait" and "Goblin Barrel" in sig.cards:
        return 60.0
    if archetype == "Split Lane" and sig.cards & {"Royal Hogs", "Wall Breakers"}:
        return 65.0

    if not sig.wins:
        return 35.0
    return 12.0


def _score_elixir(sig: _DeckSignals, archetype: str) -> float:
    lo, hi = ARCHETYPE_ELIXIR.get(archetype, (DEFAULT_ELIXIR_MIN, DEFAULT_ELIXIR_MAX))
    mid = (lo + hi) / 2.0
    avg = sig.avg_elixir
    if lo <= avg <= hi:
        # Ближе к центру диапазона — лучше
        span = max(hi - lo, 0.1)
        return 100.0 - (abs(avg - mid) / span) * 25.0
    # Вне диапазона — штраф пропорционально удалению
    dist = (lo - avg) if avg < lo else (avg - hi)
    return max(0.0, 55.0 - dist * 45.0)


def _score_anchors(sig: _DeckSignals, archetype: str) -> float:
    anchors = ARCHETYPE_ANCHORS.get(archetype, set())
    if not anchors:
        return 45.0
    hits = len(sig.cards & anchors)
    if hits == 0:
        return 8.0
    return min(100.0, 28.0 + hits * 28.0)


def _score_cycle(sig: _DeckSignals, archetype: str) -> float:
    style = _ARCHETYPE_STYLE.get(archetype, _ARCHETYPE_STYLE["Meta"])
    want = int(style["min_cycle"])
    n = sig.cycle_n
    if want <= 0:
        # Beatdown/Lava: много цикла слегка снижает «чистоту» архетипа
        if n >= 4:
            return 45.0
        return 70.0 + min(20.0, (2 - min(n, 2)) * 5.0)
    if n >= want:
        return min(100.0, 70.0 + (n - want) * 10.0)
    return max(0.0, 55.0 * (n / max(want, 1)))


def _score_support(sig: _DeckSignals, archetype: str) -> float:
    style = _ARCHETYPE_STYLE.get(archetype, _ARCHETYPE_STYLE["Meta"])
    want = int(style["support_want"])
    n = sig.support_n + sig.mini_tank_n
    if n >= want:
        return min(100.0, 75.0 + (n - want) * 8.0)
    return max(15.0, 75.0 * (n / max(want, 1)))


def _score_spells(sig: _DeckSignals, archetype: str) -> float:
    score = 40.0
    if sig.big_spell:
        score += 25.0
    if sig.small_spell:
        score += 25.0
    if sig.spell_n >= 2:
        score += 10.0

    if archetype in {"Log Bait", "Fireball Bait"}:
        if "The Log" in sig.cards or "Barbarian Barrel" in sig.cards:
            score += 15.0
        if sig.cards & _BAIT_MARKERS:
            score += 10.0
    if archetype == "Graveyard" and (
        "Poison" in sig.cards or "Freeze" in sig.cards or "Tornado" in sig.cards
    ):
        score += 12.0
    if archetype == "Siege" and sig.big_spell:
        score += 8.0

    return min(100.0, score)


def _score_buildings(sig: _DeckSignals, archetype: str) -> float:
    style = _ARCHETYPE_STYLE.get(archetype, _ARCHETYPE_STYLE["Meta"])
    want = float(style["building_want"])
    n = sig.building_n
    if want >= 0.7:
        if n >= 1:
            return 90.0 + min(10.0, (n - 1) * 5.0)
        return 15.0
    if want <= 0.2:
        # Cycle/bait: здание не обязательно
        return 75.0 if n <= 1 else 55.0
    # Средний интерес к зданиям
    if n >= 1:
        return 80.0
    return 45.0


def _score_defense(sig: _DeckSignals, archetype: str) -> float:
    style = _ARCHETYPE_STYLE.get(archetype, _ARCHETYPE_STYLE["Meta"])
    defense = str(style["defense"])
    score = 40.0

    if defense == "building":
        score += sig.building_n * 28.0
        score += min(20.0, sig.defensive_n * 10.0)
    elif defense == "cheap":
        score += min(35.0, sig.cycle_n * 12.0)
        score += min(20.0, sig.air_n * 10.0)
    elif defense == "swarm":
        score += min(30.0, sig.splash_n * 12.0)
        score += 15.0 if sig.small_spell else 0.0
    elif defense == "counter":
        score += min(25.0, sig.counterpush_n * 12.0)
        score += min(20.0, sig.splash_n * 8.0)
    elif defense == "tanky":
        score += min(25.0, sig.mini_tank_n * 12.0)
        score += min(20.0, sig.defensive_n * 10.0)
    elif defense == "ground":
        score += min(30.0, (sig.splash_n + sig.defensive_n + sig.dps_n) * 6.0)
    else:
        score += min(20.0, (sig.defensive_n + sig.air_n + sig.building_n) * 6.0)

    return min(100.0, score)


def _score_attack(sig: _DeckSignals, archetype: str) -> float:
    style = _ARCHETYPE_STYLE.get(archetype, _ARCHETYPE_STYLE["Meta"])
    attack = str(style["attack"])
    score = 35.0

    if attack == "pressure":
        if sig.primary_win in {"Hog Rider", "Miner", "Wall Breakers", "Mortar"}:
            score += 40.0
        score += min(20.0, sig.cycle_n * 5.0)
    elif attack == "tank_push":
        score += min(45.0, sig.tank_n * 22.0)
        if sig.cards & _TANK_MARKERS:
            score += 20.0
        score += min(15.0, sig.support_n * 5.0)
    elif attack == "air_push":
        if "Lava Hound" in sig.cards:
            score += 45.0
        if "Balloon" in sig.cards:
            score += 25.0
    elif attack == "bridge":
        score += min(50.0, len(sig.cards & _BRIDGE_MARKERS) * 18.0)
        score += min(20.0, sig.mini_tank_n * 8.0)
        score += min(15.0, sig.counterpush_n * 7.0)
    elif attack == "siege":
        if sig.cards & {"X-Bow", "Mortar"}:
            score += 55.0
        score += min(20.0, len(sig.cards & _SIEGE_MARKERS) * 8.0)
    elif attack == "bait":
        score += min(50.0, len(sig.cards & _BAIT_MARKERS) * 14.0)
    elif attack == "chip":
        if sig.primary_win in {"Miner", "Goblin Drill", "Graveyard"}:
            score += 40.0
        score += 15.0 if sig.big_spell else 0.0
    elif attack == "spell_bait":
        if "Graveyard" in sig.cards:
            score += 50.0
        score += 15.0 if sig.mini_tank_n else 0.0
    elif attack == "rg":
        if "Royal Giant" in sig.cards:
            score += 55.0
        if sig.cards & {"Fisherman", "Hunter"}:
            score += 20.0
    elif attack == "split":
        score += min(55.0, len(sig.cards & {"Royal Hogs", "Wall Breakers", "Miner"}) * 22.0)
    else:
        score += 20.0 if sig.wins else 0.0

    return min(100.0, score)


def score_archetype(cards: list[str], archetype: str) -> float:
    """Итоговый рейтинг 0–100 совместимости колоды с архетипом."""
    sig = _extract_signals(cards)
    total = (
        _score_win(sig, archetype) * _W_WIN
        + _score_elixir(sig, archetype) * _W_ELIXIR
        + _score_anchors(sig, archetype) * _W_ANCHORS
        + _score_cycle(sig, archetype) * _W_CYCLE
        + _score_support(sig, archetype) * _W_SUPPORT
        + _score_spells(sig, archetype) * _W_SPELLS
        + _score_buildings(sig, archetype) * _W_BUILDINGS
        + _score_defense(sig, archetype) * _W_DEFENSE
        + _score_attack(sig, archetype) * _W_ATTACK
    )
    return round(total, 2)


def detect_archetype_from_cards(cards: list[str]) -> str:
    """Выбрать наиболее вероятный архетип по мультифакторному скорингу."""
    if not cards:
        return "Meta"

    candidates = [a for a in ARCHETYPES if a != "Meta"]
    # Архетипы из якорей, которых может не быть в ARCHETYPES tuple order
    for extra in ARCHETYPE_ANCHORS:
        if extra not in candidates and extra != "Meta":
            candidates.append(extra)

    best = "Meta"
    best_score = -1.0
    for arch in candidates:
        s = score_archetype(cards, arch)
        if s > best_score:
            best_score = s
            best = arch

    meta_score = score_archetype(cards, "Meta")
    # Слабый сигнал или Meta лучше узкого ярлыка (Bridge Spam без маркеров и т.п.)
    if best_score < 42.0 or meta_score >= best_score + 2.0:
        return "Meta"

    # Архетипы с жёсткими якорями — без якоря не назначаем
    anchors = ARCHETYPE_ANCHORS.get(best, set())
    card_set = set(cards)
    if best in {"Lava", "Siege", "Bridge Spam", "Graveyard", "Log Bait", "Royal Giant", "Fireball Bait"}:
        if not (card_set & anchors):
            return "Meta"
        if best == "Lava" and not (card_set & {"Lava Hound", "Balloon"}):
            return "Meta"
        if best == "Siege" and not (card_set & {"X-Bow", "Mortar"}):
            return "Meta"
        if best == "Bridge Spam" and not (card_set & _BRIDGE_MARKERS):
            return "Meta"
        if best == "Fireball Bait" and not (card_set & {"Goblin Barrel", "Princess", "Dart Goblin"}):
            return "Meta"
        if best == "Log Bait" and "Goblin Barrel" not in card_set:
            return "Meta"

    return best
