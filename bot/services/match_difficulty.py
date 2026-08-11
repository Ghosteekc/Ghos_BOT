"""MatchDifficultyAnalyzer — индекс сложности матчапа для пользователя.

Только состав двух колод: контры, роли, архетипы, цикл, здания, воздух,
спеллы, взаимодействие win-conditions. Без истории боя и пустых «сложно».
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from bot.services.card_data import (
    WIN_CONDITIONS,
    card_has_role,
    get_card_elixir,
    is_building,
)
from bot.services.card_matchups import counters_in_deck
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_builder.archetype_detect import detect_archetype_from_cards

_BRIDGE_WINS = frozenset({
    "Hog Rider", "Battle Ram", "Ram Rider", "Royal Hogs", "Wall Breakers",
    "Elite Barbarians", "Goblin Barrel", "Skeleton Barrel", "Goblin Drill",
})
_BEATDOWN = frozenset({
    "Golem", "Lava Hound", "Electro Giant", "Elixir Golem", "Goblin Giant", "Giant",
})
_AIR_THREATS = frozenset({
    "Balloon", "Lava Hound", "Baby Dragon", "Minions", "Minion Horde", "Bats",
    "Flying Machine", "Inferno Dragon", "Skeleton Dragons", "Electro Dragon",
    "Phoenix", "Mega Minion",
})
_VALUE_SPELLS = frozenset({
    "Fireball", "Poison", "Lightning", "Rocket", "Earthquake",
})
_SMALL_SPELLS = frozenset({
    "The Log", "Zap", "Arrows", "Giant Snowball", "Barbarian Barrel", "Royal Delivery",
})
_DEF_BUILDINGS = frozenset({
    "Cannon", "Tesla", "Inferno Tower", "Bomb Tower", "Goblin Cage",
    "Tombstone", "Goblin Hut", "Barbarian Hut",
})

# Мягкие «контры» цикла — не считаем надёжным ответом на WC.
_SOFT_ANSWERS = frozenset({
    "Ice Golem", "Ice Spirit", "Skeletons", "Electro Spirit", "Heal Spirit",
    "Fire Spirit", "Bats",
})

# Спелл → карты, на которых он реально держит ценность.
_SPELL_VALUE_TARGETS: dict[str, frozenset[str]] = {
    "Fireball": frozenset({
        "Flying Machine", "Firecracker", "Musketeer", "Wizard", "Witch",
        "Magic Archer", "Dart Goblin", "Three Musketeers", "Mother Witch",
        "Zappies", "Archer Queen",
    }),
    "Poison": frozenset({
        "Graveyard", "Goblin Barrel", "Skeleton Barrel", "Furnace",
        "Goblin Hut", "Witch", "Night Witch", "Tombstone",
    }),
    "Lightning": frozenset({
        "Inferno Tower", "Inferno Dragon", "Sparky", "Wizard", "Witch",
        "Electro Wizard", "Musketeer", "Three Musketeers", "Archer Queen",
    }),
    "Rocket": frozenset({
        "X-Bow", "Mortar", "Sparky", "Three Musketeers", "Elixir Collector",
    }),
    "Earthquake": frozenset({
        "X-Bow", "Mortar", "Tesla", "Cannon", "Inferno Tower", "Bomb Tower",
        "Goblin Cage", "Tombstone",
    }),
}

DIFFICULTY_RATINGS = (
    "Очень лёгкий",
    "Лёгкий",
    "Равный",
    "Сложный",
    "Очень сложный",
)


def _ru(card: str) -> str:
    return card_name_ru(card) or card


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, round(value))))


def _wins(deck: list[str]) -> list[str]:
    return [c for c in deck if c in WIN_CONDITIONS or card_has_role(c, "win_condition")]


def _primary_win(deck: list[str]) -> str | None:
    wins = _wins(deck)
    if not wins:
        return None
    return sorted(wins, key=lambda c: (get_card_elixir(c), c))[0]


def _effective_cycle(deck: list[str]) -> int:
    costs = sorted(get_card_elixir(c) for c in deck)
    return int(sum(costs[:4])) if len(costs) >= 4 else int(sum(costs))


def _buildings(deck: list[str]) -> list[str]:
    return [c for c in deck if c in _DEF_BUILDINGS or is_building(c)]


def _air_threats(deck: list[str]) -> list[str]:
    from bot.services.card_data import card_is_flying

    return [c for c in deck if c in _AIR_THREATS or card_is_flying(c)]


def _air_defense(deck: list[str]) -> list[str]:
    from bot.services.card_data import card_can_target_air

    return [c for c in deck if card_can_target_air(c)]


def _value_spells(deck: list[str]) -> list[str]:
    return [c for c in deck if c in _VALUE_SPELLS or card_has_role(c, "big_spell")]


def _small_spells(deck: list[str]) -> list[str]:
    return [
        c for c in deck
        if c in _SMALL_SPELLS or card_has_role(c, "small_spell")
    ]


def _rating_for(difficulty: int) -> str:
    if difficulty <= 19:
        return "Очень лёгкий"
    if difficulty <= 39:
        return "Лёгкий"
    if difficulty <= 59:
        return "Равный"
    if difficulty <= 79:
        return "Сложный"
    return "Очень сложный"


@dataclass
class MatchDifficultyReport:
    difficulty: int = 50
    rating: str = "Равный"
    reasons: list[str] = field(default_factory=list)
    # Факторы 0–100 для прозрачности (необязательны UI, но полезны API).
    factors: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def has_content(self) -> bool:
        return bool(self.reasons) or self.difficulty != 50


@dataclass
class _Factor:
    key: str
    delta: float
    reason: str | None = None


def _reliable_answers(counters: list[str]) -> list[str]:
    return [c for c in counters if c not in _SOFT_ANSWERS]


def _wc_counter_pressure(user: list[str], opp: list[str]) -> list[_Factor]:
    """Насколько соперник отвечает на наши WC / мы на его."""
    factors: list[_Factor] = []
    user_wins = _wins(user)
    opp_wins = _wins(opp)

    for win in user_wins[:2]:
        strong, partial = counters_in_deck(win, opp)
        strong = _reliable_answers(strong)
        partial = _reliable_answers(partial)
        if len(strong) >= 2:
            factors.append(_Factor(
                "win_condition_interaction",
                20,
                f"У противника два надёжных ответа на {_ru(win)}.",
            ))
        elif len(strong) == 1:
            factors.append(_Factor(
                "win_condition_interaction",
                10,
                f"У противника надёжный ответ на {_ru(win)} ({_ru(strong[0])}).",
            ))
        elif len(partial) >= 2 and not strong:
            factors.append(_Factor(
                "win_condition_interaction",
                7,
                f"У противника несколько частичных ответов на {_ru(win)}.",
            ))
        elif not strong and not partial:
            factors.append(_Factor(
                "win_condition_interaction",
                -14,
                f"У противника нет ответа на {_ru(win)}.",
            ))

    for threat in opp_wins[:2]:
        strong, partial = counters_in_deck(threat, user)
        strong = _reliable_answers(strong)
        partial = _reliable_answers(partial)
        if not strong and not partial:
            factors.append(_Factor(
                "counter_database",
                16,
                f"Нет счётчика на {_ru(threat)} соперника.",
            ))
        elif not strong and partial:
            factors.append(_Factor(
                "counter_database",
                8,
                f"Только слабый ответ на {_ru(threat)} ({_ru(partial[0])}).",
            ))
        elif len(strong) >= 2:
            factors.append(_Factor(
                "counter_database",
                -10,
                f"Есть надёжные ответы на {_ru(threat)}.",
            ))
        elif len(strong) == 1:
            factors.append(_Factor(
                "counter_database",
                -6,
                f"Есть ответ на {_ru(threat)} ({_ru(strong[0])}).",
            ))

    return factors


def _building_factor(user: list[str], opp: list[str]) -> list[_Factor]:
    factors: list[_Factor] = []
    opp_bld = _buildings(opp)
    user_bld = _buildings(user)
    user_bridge = [c for c in user if c in _BRIDGE_WINS]
    opp_bridge = [c for c in opp if c in _BRIDGE_WINS]

    # Не дублируем, если здание уже учтено как надёжный ответ на bridge-WC.
    if user_bridge and opp_bld:
        win = user_bridge[0]
        strong, _ = counters_in_deck(win, opp)
        strong = _reliable_answers(strong)
        if not any(b in strong for b in opp_bld):
            factors.append(_Factor(
                "building_availability",
                12,
                f"У противника есть {_ru(opp_bld[0])} против {_ru(win)}.",
            ))
    if user_bridge and not opp_bld:
        factors.append(_Factor(
            "building_availability",
            -8,
            f"У противника нет здания против {_ru(user_bridge[0])}.",
        ))
    if opp_bridge and not user_bld:
        factors.append(_Factor(
            "building_availability",
            12,
            f"Нет здания против {_ru(opp_bridge[0])} соперника.",
        ))
    if opp_bridge and user_bld:
        strong, _ = counters_in_deck(opp_bridge[0], user)
        if user_bld[0] not in _reliable_answers(strong):
            factors.append(_Factor(
                "building_availability",
                -6,
                f"{_ru(user_bld[0])} закрывает {_ru(opp_bridge[0])}.",
            ))
    return factors


def _air_factor(user: list[str], opp: list[str]) -> list[_Factor]:
    factors: list[_Factor] = []
    opp_air = _air_threats(opp)
    user_air = _air_threats(user)
    user_aa = _air_defense(user)
    opp_aa = _air_defense(opp)

    # Воздушное преимущество соперника: есть air-угрозы, у нас слабая ПВО.
    if opp_air and len(user_aa) == 0:
        threat = opp_air[0]
        factors.append(_Factor(
            "air_control",
            14,
            f"У противника преимущество в воздухе ({_ru(threat)}) — нет ПВО.",
        ))
    elif opp_air and len(user_aa) < len(opp_air):
        factors.append(_Factor(
            "air_control",
            10,
            "У противника преимущество в воздухе.",
        ))
    elif user_air and len(opp_aa) == 0:
        factors.append(_Factor(
            "air_control",
            -12,
            f"Соперник без ПВО против {_ru(user_air[0])}.",
        ))
    return factors


def _cycle_pressure_factor(user: list[str], opp: list[str]) -> list[_Factor]:
    factors: list[_Factor] = []
    user_cycle = _effective_cycle(user)
    opp_cycle = _effective_cycle(opp)
    user_avg = sum(get_card_elixir(c) for c in user) / len(user)
    opp_avg = sum(get_card_elixir(c) for c in opp) / len(opp)

    if opp_cycle <= user_cycle - 3 or opp_avg <= user_avg - 0.6:
        factors.append(_Factor(
            "cycle_speed",
            11,
            f"Соперник быстрее циклит ({opp_cycle} vs ваш {user_cycle}).",
        ))
    elif user_cycle <= opp_cycle - 3 or user_avg <= opp_avg - 0.6:
        factors.append(_Factor(
            "cycle_speed",
            -9,
            f"Вы быстрее циклите ({user_cycle} vs {opp_cycle}).",
        ))

    # Давление: у соперника больше bridge/punish угроз при нашем медленном цикле.
    opp_pressure = sum(1 for c in opp if c in _BRIDGE_WINS or c in _BEATDOWN)
    user_pressure = sum(1 for c in user if c in _BRIDGE_WINS or c in _BEATDOWN)
    if opp_pressure >= 2 and opp_cycle <= 9 and user_cycle >= opp_cycle + 2:
        factors.append(_Factor(
            "pressure",
            9,
            "Соперник давит быстрее за счёт цикла и угроз.",
        ))
    elif user_pressure >= 2 and user_cycle <= 8 and opp_cycle >= user_cycle + 2:
        factors.append(_Factor(
            "pressure",
            -7,
            "Ваше давление по темпу выше.",
        ))
    return factors


def _spell_advantage_factor(user: list[str], opp: list[str]) -> list[_Factor]:
    factors: list[_Factor] = []
    user_spells = _value_spells(user)
    opp_spells = _value_spells(opp)

    for spell in user_spells:
        targets = _SPELL_VALUE_TARGETS.get(spell, frozenset())
        hits = [t for t in targets if t in opp]
        if not hits and spell in _VALUE_SPELLS:
            # Нет ценности спелла + у соперника есть чем наказать трату.
            opp_can_punish = bool(_wins(opp)) or any(c in _BRIDGE_WINS for c in opp)
            if opp_can_punish:
                factors.append(_Factor(
                    "spell_advantage",
                    12,
                    f"Нет возможности быстро наказать после {_ru(spell)}.",
                ))
            else:
                factors.append(_Factor(
                    "spell_advantage",
                    6,
                    f"{_ru(spell)} почти без ценности в этом матчапе.",
                ))
            break  # один вывод по спеллам достаточно
        if hits and len(hits) >= 2:
            factors.append(_Factor(
                "spell_advantage",
                -8,
                f"{_ru(spell)} бьёт несколько целей соперника.",
            ))
            break

    # Bait vs наш единственный малый спелл.
    user_small = _small_spells(user)
    bait = [c for c in opp if c in {"Goblin Barrel", "Princess", "Goblin Gang", "Dart Goblin", "Skeleton Barrel"}]
    if len(bait) >= 2 and len(user_small) <= 1:
        factors.append(_Factor(
            "spell_advantage",
            10,
            "Bait-угрозы соперника перегружают ваш малый спелл.",
        ))
    elif len([c for c in user if c in {"Goblin Barrel", "Princess", "Goblin Gang", "Dart Goblin"}]) >= 2 and len(_small_spells(opp)) <= 1:
        factors.append(_Factor(
            "spell_advantage",
            -9,
            "Ваш bait перегружает малый спелл соперника.",
        ))

    if opp_spells and not user_spells:
        factors.append(_Factor(
            "spell_advantage",
            7,
            f"У соперника есть большой спелл ({_ru(opp_spells[0])}), у вас нет.",
        ))
    return factors


def _archetype_factor(user: list[str], opp: list[str]) -> list[_Factor]:
    factors: list[_Factor] = []
    user_arch = detect_archetype_from_cards(user)
    opp_arch = detect_archetype_from_cards(opp)

    # Известные структурные дисбалансы архетипов (без «рандома»).
    hard = {
        ("Cycle", "Control"): (8, "Контроль соперника душит цикл-давление."),
        ("Cycle", "Siege"): (10, "Осада соперника неудобна для цикла без ответа на здание."),
        ("Beatdown", "Cycle"): (9, "Быстрый цикл соперника наказывает медленный набор."),
        ("Lava", "Control"): (8, "Контроль с ПВО режет воздушный план."),
        ("Log Bait", "Control"): (7, "Контроль закрывает bait-угрозы."),
        ("Bridge Spam", "Control"): (8, "Контроль стабильно отвечает на bridge-спам."),
    }
    easy = {
        ("Cycle", "Beatdown"): (-9, "Ваш цикл быстрее наказывает тяжёлый beatdown."),
        ("Control", "Beatdown"): (-8, "Контроль удобен против тяжёлого пуша."),
        ("Siege", "Beatdown"): (-7, "Осада наказывает медленный набор."),
        ("Log Bait", "Bridge Spam"): (-6, "Bait вытягивает ответы bridge-спама."),
    }

    key = (user_arch, opp_arch)
    if key in hard:
        delta, text = hard[key]
        # Подтверждаем структурно: иначе не пишем.
        if key[1] == "Control" and (_buildings(opp) or _value_spells(opp)):
            factors.append(_Factor("archetypes", delta, text))
        elif key[1] == "Siege" and any(c in opp for c in ("X-Bow", "Mortar")):
            factors.append(_Factor("archetypes", delta, text))
        elif key[1] == "Cycle" and _effective_cycle(opp) <= 8:
            factors.append(_Factor("archetypes", delta, text))
        else:
            factors.append(_Factor("archetypes", delta, text))
    elif key in easy:
        delta, text = easy[key]
        factors.append(_Factor("archetypes", delta, text))

    return factors


def _card_role_factors(user: list[str], opp: list[str]) -> list[_Factor]:
    """Ролевые пробелы, влияющие на общий MatchupEvaluation."""
    factors: list[_Factor] = []
    if any(c in _BEATDOWN or card_has_role(c, "tank") for c in opp):
        if not any(card_has_role(c, "anti_tank") for c in user):
            factors.append(_Factor(
                "card_roles",
                9,
                "Нет anti-tank роли против тяжёлых танков соперника.",
            ))
    if any(card_has_role(c, "swarm") for c in opp) or any(
        c in {"Skeleton Army", "Goblin Gang", "Minion Horde", "Bats"} for c in opp
    ):
        if not any(card_has_role(c, "splash") or card_has_role(c, "anti_swarm") for c in user):
            factors.append(_Factor(
                "card_roles",
                8,
                "Нет splash / anti-swarm против роя соперника.",
            ))
    return factors


class MatchDifficultyAnalyzer:
    """Совместимый адаптер к единому MatchupEvaluation."""

    @staticmethod
    def analyze(user_deck: list[str], opponent_deck: list[str]) -> MatchDifficultyReport:
        from bot.services.matchup_evaluation import evaluate_matchup

        evaluation = evaluate_matchup(user_deck, opponent_deck)
        return MatchDifficultyReport(
            difficulty=evaluation.difficulty,
            rating=evaluation.rating,
            reasons=evaluation.reasons,
            factors=evaluation.factors,
        )


def analyze_match_difficulty(
    user_deck: list[str],
    opponent_deck: list[str],
) -> MatchDifficultyReport:
    return MatchDifficultyAnalyzer.analyze(user_deck, opponent_deck)
