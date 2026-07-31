"""ElixirEfficiencyAnalyzer — профиль эликсира по составу колоды.

Только структура колоды (стоимости, роли, win-conditions).
Без истории боя и случайных оценок.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from bot.services.card_data import WIN_CONDITIONS, card_has_role, get_card_elixir
from bot.services.card_names_ru import card_name_ru

ELIXIR_PROFILES = (
    "Fast Cycle",
    "Medium Cycle",
    "Heavy Control",
    "Heavy Beatdown",
    "Bridge Pressure",
    "Split Pressure",
)

# Тяжёлые beatdown-танки — сила в дабл-эликсире.
_BEATDOWN_TANKS = frozenset({
    "Golem", "Lava Hound", "Electro Giant", "Elixir Golem", "Goblin Giant",
})
_SEMI_BEATDOWN = frozenset({"Giant", "P.E.K.K.A", "Goblin Machine"})

# Дешёвые/средние WC для наказаний и цикла.
_PUNISH_WINS = frozenset({
    "Hog Rider", "Goblin Barrel", "Wall Breakers", "Royal Hogs", "Miner",
    "Battle Ram", "Skeleton Barrel", "Goblin Drill", "Mortar", "Ram Rider",
    "Elite Barbarians", "Boss Bandit",
})

# Bridge-spam угрозы (давление на мосту).
_BRIDGE_THREATS = frozenset({
    "Battle Ram", "Bandit", "Royal Ghost", "Ram Rider", "Dark Prince",
    "Elite Barbarians", "Mega Knight", "Boss Bandit", "Golden Knight",
})

# Bait / split-lane инструменты.
_BAIT_THREATS = frozenset({
    "Goblin Barrel", "Princess", "Goblin Gang", "Dart Goblin",
    "Skeleton Barrel", "Goblin Demolisher", "Goblin Curse",
})
_SPLIT_WINS = frozenset({"Royal Hogs", "Goblin Barrel", "Wall Breakers", "Three Musketeers"})

# Инструменты овертайма / добивания.
_OVERTIME_TOOLS = frozenset({
    "Poison", "Rocket", "Earthquake", "Lightning", "Miner",
    "X-Bow", "Mortar", "Graveyard", "Royal Giant", "Furnace",
})


def _ru(card: str) -> str:
    return card_name_ru(card) or card


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, round(value))))


def _wins(cards: list[str]) -> list[str]:
    return [c for c in cards if c in WIN_CONDITIONS or card_has_role(c, "win_condition")]


def _primary_win(cards: list[str]) -> str | None:
    wins = _wins(cards)
    if not wins:
        return None
    # Предпочитаем самый дешёвый WC как ось давления/цикла.
    return sorted(wins, key=lambda c: (get_card_elixir(c), c))[0]


@dataclass
class ElixirEfficiencyReport:
    average_cost: float = 0.0
    effective_cycle: int = 0
    cheap_rotation: int = 0
    punish_speed: int = 0
    recovery_speed: int = 0
    double_elixir_power: int = 0
    overtime_strength: int = 0
    elixir_profile: str = "Medium Cycle"
    explanations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _metrics(cards: list[str]) -> dict:
    costs = [get_card_elixir(c) for c in cards]
    average_cost = round(sum(costs) / len(costs), 2)
    sorted_costs = sorted(costs)
    effective_cycle = int(sum(sorted_costs[:4]))

    le1 = sum(1 for x in costs if x <= 1)
    le2 = sum(1 for x in costs if x <= 2)
    le3 = sum(1 for x in costs if x <= 3)
    # Детерминированная формула ротации: вес самых дешёвых карт.
    cheap_rotation = _clamp(le1 * 18 + le2 * 16 + (le3 - le2) * 6)

    punish_wins = [c for c in cards if c in _PUNISH_WINS]
    if punish_wins:
        wc_cost = min(get_card_elixir(c) for c in punish_wins)
        punish_speed = _clamp(
            100 - wc_cost * 10 - max(0, effective_cycle - 4) * 5 + le2 * 8
        )
    else:
        # Без punish-WC скорость наказания низкая (только цикл/дешёвые карты).
        punish_speed = _clamp(le2 * 10 + max(0, 40 - effective_cycle * 3))

    recovery_speed = _clamp(
        115 - average_cost * 18 - effective_cycle * 3 + le2 * 12
    )

    heavy_mass = 0
    for c, cost in zip(cards, costs):
        if cost >= 6 and (
            c in _BEATDOWN_TANKS
            or c in _SEMI_BEATDOWN
            or card_has_role(c, "tank")
            or card_has_role(c, "win_condition")
        ):
            heavy_mass += cost
        elif cost >= 5 and (
            c in _BEATDOWN_TANKS
            or c in _SEMI_BEATDOWN
            or card_has_role(c, "tank")
            or c == "Three Musketeers"
        ):
            heavy_mass += cost
        elif cost >= 5 and card_has_role(c, "big_spell"):
            heavy_mass += cost // 2

    beatdown_n = sum(1 for c in cards if c in _BEATDOWN_TANKS | _SEMI_BEATDOWN)
    double_elixir_power = _clamp(heavy_mass * 7 + beatdown_n * 18)

    ot_tools = sum(1 for c in cards if c in _OVERTIME_TOOLS)
    has_building = any(card_has_role(c, "building") for c in cards)
    overtime_strength = _clamp(
        ot_tools * 16
        + double_elixir_power * 0.35
        + (12 if has_building else 0)
        + (10 if any(card_has_role(c, "big_spell") for c in cards) else 0)
    )

    return {
        "average_cost": average_cost,
        "effective_cycle": effective_cycle,
        "cheap_rotation": cheap_rotation,
        "punish_speed": punish_speed,
        "recovery_speed": recovery_speed,
        "double_elixir_power": double_elixir_power,
        "overtime_strength": overtime_strength,
        "le2": le2,
        "le3": le3,
        "costs": costs,
    }


def _classify(cards: list[str], m: dict) -> str:
    """Профиль строго по структуре: пороги + наличие ролей/WC."""
    avg = m["average_cost"]
    cycle = m["effective_cycle"]
    le2 = m["le2"]
    card_set = set(cards)
    primary = _primary_win(cards)

    has_beatdown = bool(card_set & _BEATDOWN_TANKS) or (
        bool(card_set & _SEMI_BEATDOWN) and avg >= 3.8
    )
    bait_n = sum(1 for c in cards if c in _BAIT_THREATS)
    bridge_n = sum(1 for c in cards if c in _BRIDGE_THREATS)
    has_split_win = bool(card_set & _SPLIT_WINS)
    has_control_core = (
        any(card_has_role(c, "building") for c in cards)
        or any(c in {"X-Bow", "Mortar", "Graveyard", "Royal Giant"} for c in cards)
        or (
            any(card_has_role(c, "big_spell") for c in cards)
            and avg >= 3.5
            and m["double_elixir_power"] < 55
        )
    )

    # Порядок: сначала уникальные тяжёлые/сплит/bridge, затем цикл.
    if has_beatdown and avg >= 3.7 and m["double_elixir_power"] >= 45:
        return "Heavy Beatdown"

    if has_split_win and (bait_n >= 2 or "Royal Hogs" in card_set or "Three Musketeers" in card_set):
        return "Split Pressure"

    if bridge_n >= 2 and avg <= 4.0 and not has_beatdown:
        return "Bridge Pressure"

    if (
        avg <= 3.2
        and cycle <= 8
        and le2 >= 2
        and primary is not None
        and primary in _PUNISH_WINS
    ):
        return "Fast Cycle"

    if has_control_core and avg >= 3.4 and cycle >= 9:
        return "Heavy Control"

    if avg <= 3.5 and cycle <= 10 and le2 >= 1:
        return "Medium Cycle"

    if has_control_core or (avg >= 3.6 and m["recovery_speed"] <= 45):
        return "Heavy Control"

    if avg >= 3.8:
        return "Heavy Beatdown" if m["double_elixir_power"] >= 40 else "Heavy Control"

    return "Medium Cycle"


def _explanations(cards: list[str], m: dict, profile: str) -> list[str]:
    """Только выводы с явными предпосылками в составе."""
    out: list[str] = []
    primary = _primary_win(cards)
    le2 = m["le2"]
    avg = m["average_cost"]
    cycle = m["effective_cycle"]

    if (
        primary
        and primary in _PUNISH_WINS
        and cycle <= 8
        and le2 >= 2
    ):
        out.append(f"Колода быстро возвращает {_ru(primary)}.")

    if profile == "Heavy Beatdown" or (
        m["double_elixir_power"] >= 60 and avg >= 3.8
    ):
        out.append("Колода раскрывается после двойного эликсира.")

    if avg >= 4.0 or cycle >= 12:
        out.append("Каждая ошибка стоит дорого.")

    if m["recovery_speed"] <= 35 or (avg >= 3.8 and le2 <= 1):
        out.append("Тяжело догонять по темпу.")

    if profile == "Split Pressure":
        if "Royal Hogs" in cards:
            out.append(f"{_ru('Royal Hogs')} давят сплитом по двум линиям.")
        elif "Goblin Barrel" in cards:
            out.append("Сплит-давление через бочку и bait-угрозы.")
        elif "Three Musketeers" in cards:
            out.append(f"{_ru('Three Musketeers')} требуют сплит и запас эликсира.")

    if profile == "Bridge Pressure":
        threats = [c for c in cards if c in _BRIDGE_THREATS][:2]
        if threats:
            names = " / ".join(_ru(c) for c in threats)
            out.append(f"Давление строится через bridge-угрозы ({names}).")

    if profile == "Fast Cycle" and m["punish_speed"] >= 55:
        out.append("Быстрый цикл позволяет наказывать ошибки соперника.")

    if profile == "Heavy Control" and any(card_has_role(c, "building") for c in cards):
        bld = next(c for c in cards if card_has_role(c, "building"))
        out.append(f"Контроль опирается на {_ru(bld)} и выгодные обмены.")

    if m["overtime_strength"] >= 55 and any(c in _OVERTIME_TOOLS for c in cards):
        tool = next(c for c in cards if c in _OVERTIME_TOOLS)
        if profile in {"Heavy Control", "Heavy Beatdown", "Medium Cycle"}:
            out.append(f"В овертайме сильна ценность {_ru(tool)}.")

    # Уникальность, лимит
    seen: set[str] = set()
    unique: list[str] = []
    for line in out:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique[:6]


class ElixirEfficiencyAnalyzer:
    """Публичный API анализа эликсир-эффективности колоды."""

    @staticmethod
    def analyze(cards: list[str]) -> ElixirEfficiencyReport:
        if len(cards) < 8:
            return ElixirEfficiencyReport()

        deck = list(cards)
        m = _metrics(deck)
        profile = _classify(deck, m)
        if profile not in ELIXIR_PROFILES:
            profile = "Medium Cycle"

        return ElixirEfficiencyReport(
            average_cost=m["average_cost"],
            effective_cycle=m["effective_cycle"],
            cheap_rotation=m["cheap_rotation"],
            punish_speed=m["punish_speed"],
            recovery_speed=m["recovery_speed"],
            double_elixir_power=m["double_elixir_power"],
            overtime_strength=m["overtime_strength"],
            elixir_profile=profile,
            explanations=_explanations(deck, m, profile),
        )


def analyze_elixir_efficiency(cards: list[str]) -> ElixirEfficiencyReport:
    return ElixirEfficiencyAnalyzer.analyze(cards)
