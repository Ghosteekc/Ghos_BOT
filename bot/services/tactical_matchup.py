"""TacticalMatchupAnalyzer — тактический разбор пары колод.

Только факты из состава A/B: роли, win-conditions, синергии, контры,
архетипы, GamePlan. Никакого урона, случайных эвристик и шаблонных советов
без предпосылок в обеих колодах.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from bot.services.card_data import (
    COUNTERS,
    WIN_CONDITIONS,
    card_has_role,
    get_card_elixir,
    is_building,
    is_pure_spell,
    is_spam_card,
)
from bot.services.card_matchups import card_counters_target, counters_in_deck, synergy_between
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_builder.archetype_detect import detect_archetype_from_cards
from bot.services.deck_builder.constants import KNOWN_SYNERGY_PAIRS, SYNERGY_STRONG
from bot.services.deck_game_plan import GamePlan, build_game_plan
from bot.services.deck_intent import DeckIntentEngine
from bot.services.spell_hold import FIREBALL_HOLD_PRIORITY, pick_fireball_hold

# Большие спеллы, которыми держат ценность до ключевой цели.
_VALUE_SPELLS = frozenset({
    "Fireball", "Poison", "Lightning", "Rocket", "Earthquake",
})

# Приоритет целей (раньше = важнее держать спелл).
_SPELL_HOLD_TARGETS: dict[str, tuple[str, ...]] = {
    "Fireball": FIREBALL_HOLD_PRIORITY,
    "Poison": (
        "Graveyard", "Goblin Barrel", "Skeleton Barrel", "Furnace",
        "Goblin Hut", "Barbarian Hut", "Witch", "Night Witch", "Tombstone",
    ),
    "Lightning": (
        "Inferno Tower", "Inferno Dragon", "Sparky", "Three Musketeers",
        "Archer Queen", "Wizard", "Witch", "Electro Wizard", "Musketeer",
    ),
    "Rocket": (
        "X-Bow", "Mortar", "Sparky", "Three Musketeers", "Elixir Collector",
    ),
    "Earthquake": (
        "X-Bow", "Mortar", "Tesla", "Cannon", "Inferno Tower", "Bomb Tower",
        "Goblin Cage", "Tombstone",
    ),
}

# Защитные здания, которые реально стопают bridge-win.
_DEFENSIVE_BUILDINGS = frozenset({
    "Cannon", "Tesla", "Inferno Tower", "Bomb Tower", "Goblin Cage",
    "Tombstone", "Goblin Hut", "Barbarian Hut", "Cannon Cart",
})

_BRIDGE_WINS = frozenset({
    "Hog Rider", "Battle Ram", "Ram Rider", "Royal Hogs", "Wall Breakers",
    "Elite Barbarians", "Goblin Barrel", "Skeleton Barrel",
})
_BEATDOWN_TANKS = frozenset({
    "Golem", "Lava Hound", "Electro Giant", "Elixir Golem", "Giant", "Goblin Giant",
})
_SIEGE = frozenset({"X-Bow", "Mortar"})

# Классические защитные комбо: (пара, предикат контекста соперника, текст).
_DEFENSE_COMBOS: tuple[tuple[frozenset[str], callable, str], ...] = (
    (
        frozenset({"Executioner", "Tornado"}),
        lambda opp: _opp_needs_swarm_clear(opp) or _opp_has_air(opp),
        "{a} + {b} — ключевая защита.",
    ),
    (
        frozenset({"Wizard", "Tornado"}),
        lambda opp: _opp_needs_swarm_clear(opp) or _opp_has_air(opp),
        "{a} + {b} — ключевая защита от роя/воздуха.",
    ),
    (
        frozenset({"Baby Dragon", "Tornado"}),
        lambda opp: _opp_needs_swarm_clear(opp) or "Balloon" in opp or "Graveyard" in opp,
        "{a} + {b} — ключевая защита.",
    ),
    (
        frozenset({"Bowler", "Tornado"}),
        lambda opp: any(c in opp for c in _BRIDGE_WINS | {"Goblin Barrel", "Royal Hogs"}),
        "{a} + {b} — ключевая защита от bridge-угроз.",
    ),
    (
        frozenset({"Valkyrie", "Tornado"}),
        lambda opp: _opp_needs_swarm_clear(opp) or "Graveyard" in opp,
        "{a} + {b} — сильная защита от спама/GY.",
    ),
)


def _ru(card: str) -> str:
    return card_name_ru(card) or card


def _combo_ru(text: str) -> str:
    """Переводит 'CardA + CardB' в русские имена, если обе карты известны."""
    if " + " not in text:
        return text
    left, right = text.split(" + ", 1)
    left, right = left.strip(), right.strip()
    if left and right and left[0].isupper() and right[0].isupper():
        return f"{_ru(left)} + {_ru(right)}"
    return text


def _pair_is_known(a: str, b: str) -> bool:
    key = frozenset({a, b})
    if key in KNOWN_SYNERGY_PAIRS and KNOWN_SYNERGY_PAIRS[key] >= SYNERGY_STRONG:
        return True
    return synergy_between(a, b) == "strong"


def _deck_def_buildings(deck: list[str]) -> list[str]:
    return [c for c in deck if c in _DEFENSIVE_BUILDINGS or is_building(c)]


def _deck_wins(deck: list[str]) -> list[str]:
    return [c for c in deck if c in WIN_CONDITIONS or card_has_role(c, "win_condition")]


def _deck_small_spells(deck: list[str]) -> list[str]:
    return [
        c for c in deck
        if card_has_role(c, "small_spell") or c in {
            "The Log", "Zap", "Arrows", "Giant Snowball", "Barbarian Barrel", "Royal Delivery",
        }
    ]


def _opp_needs_swarm_clear(opp: list[str]) -> bool:
    return any(is_spam_card(c) or card_has_role(c, "swarm") for c in opp)


def _opp_has_air(opp: list[str]) -> bool:
    from bot.services.card_data import card_is_flying

    return any(card_is_flying(c) for c in opp)


def _spell_answers_target(spell: str, target: str) -> bool:
    if spell in (COUNTERS.get(target) or []):
        return True
    if card_counters_target(spell, target) in {"strong", "partial"}:
        return True
    # Явные hold-пары, которые логичны по роли даже без записи в COUNTERS.
    if spell == "Poison" and target in {"Graveyard", "Goblin Barrel", "Skeleton Barrel"}:
        return True
    if spell == "Fireball" and target in _SPELL_HOLD_TARGETS["Fireball"]:
        return True
    if spell == "Earthquake" and (is_building(target) or target in _DEFENSIVE_BUILDINGS | _SIEGE):
        return True
    return False


@dataclass
class DangerCard:
    name: str
    name_ru: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TacticalMatchupReport:
    early_game: list[str] = field(default_factory=list)
    mid_game: list[str] = field(default_factory=list)
    late_game: list[str] = field(default_factory=list)
    pressure_points: list[str] = field(default_factory=list)
    critical_interactions: list[str] = field(default_factory=list)
    danger_cards: list[DangerCard] = field(default_factory=list)
    best_openings: list[str] = field(default_factory=list)
    worst_mistakes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "early_game": list(self.early_game),
            "mid_game": list(self.mid_game),
            "late_game": list(self.late_game),
            "pressure_points": list(self.pressure_points),
            "critical_interactions": list(self.critical_interactions),
            "danger_cards": [d.to_dict() for d in self.danger_cards],
            "best_openings": list(self.best_openings),
            "worst_mistakes": list(self.worst_mistakes),
        }

    def has_content(self) -> bool:
        return bool(
            self.early_game
            or self.mid_game
            or self.late_game
            or self.pressure_points
            or self.critical_interactions
            or self.danger_cards
            or self.best_openings
            or self.worst_mistakes
        )


def _add(bucket: list[str], line: str, *, limit: int = 6) -> None:
    if line and line not in bucket and len(bucket) < limit:
        bucket.append(line)


def _mentions_pair(text: str, a: str, b: str) -> bool:
    """True, если в тексте уже есть обе карты пары (RU или EN)."""
    low = text.lower()
    tokens = {_ru(a).lower(), a.lower(), _ru(b).lower(), b.lower()}
    return sum(1 for t in tokens if t and t in low) >= 2


def _spell_hold_rules(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    # Fireball — отдельная логика приоритета (варвары > ведьма и т.п.).
    if "Fireball" in user:
        focus, reason = pick_fireball_hold(user, opp)
        if focus:
            _add(out.critical_interactions, f"Не трать {_ru('Fireball')}: {reason}")
            _add(out.worst_mistakes, f"Ранний {_ru('Fireball')} до {_ru(focus)} — потеря ценности.")

    for spell, targets in _SPELL_HOLD_TARGETS.items():
        if spell == "Fireball" or spell not in user:
            continue
        valid = [t for t in targets if t in opp and _spell_answers_target(spell, t)]
        if not valid:
            continue
        focus = valid[0]
        _add(out.critical_interactions, f"Не трать {_ru(spell)} до появления {_ru(focus)}.")
        _add(out.worst_mistakes, f"Ранний {_ru(spell)} до {_ru(focus)} — потеря ценности.")
        if focus == "Graveyard" and spell == "Poison":
            _add(out.late_game, f"В дабл-эликсире {_ru(focus)} опаснее — {_ru(spell)} в руке.")


def _defense_combo_rules(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    for pair, context_ok, template in _DEFENSE_COMBOS:
        if not pair.issubset(user):
            continue
        if not context_ok(opp):
            continue
        a, b = sorted(pair)
        if not (_pair_is_known(a, b) or "Tornado" in pair):
            continue
        # Только critical_interactions — не дублируем в mid.
        _add(out.critical_interactions, template.format(a=_ru(a), b=_ru(b)))


def _building_vs_bridge_rules(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    opp_buildings = _deck_def_buildings(opp)
    if not opp_buildings:
        return
    for win in (c for c in user if c in _BRIDGE_WINS):
        bld = opp_buildings[0]
        # Позитив — openings; инверсия — mistakes. Не в early/pressure.
        _add(out.best_openings, f"{_ru(win)} лучше пускать после траты {_ru(bld)}.")
        _add(out.worst_mistakes, f"Пускать {_ru(win)} в готовое {_ru(bld)} — проигрышный обмен.")


def _bait_rules(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    opp_small = _deck_small_spells(opp)
    if not opp_small:
        return
    bait_threats = [
        c for c in user
        if c in {
            "Goblin Barrel", "Princess", "Goblin Gang", "Skeleton Barrel",
            "Dart Goblin", "Goblin Demolisher",
        }
    ]
    if "Goblin Barrel" not in bait_threats and len(bait_threats) < 2:
        return
    spell = opp_small[0]
    primary = "Goblin Barrel" if "Goblin Barrel" in bait_threats else bait_threats[0]
    others = [c for c in bait_threats if c != primary]
    if not others:
        return
    secondary = others[0]
    # Только pressure — не mid + critical одновременно.
    _add(
        out.pressure_points,
        f"После траты {_ru(spell)} соперника дави {_ru(secondary)} "
        f"(связка с {_ru(primary)}).",
    )


def _hold_answer_for_win(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    for threat in _deck_wins(opp):
        strong, partial = counters_in_deck(threat, user)
        answers = strong or partial
        if not answers:
            continue
        if threat == "Graveyard" and "Poison" in user:
            _add(out.critical_interactions, f"Против {_ru(threat)} держи {_ru('Poison')}.")
            continue
        answer = answers[0]
        if is_building(answer) or answer in _DEFENSIVE_BUILDINGS or card_has_role(answer, "anti_tank") or answer in {
            "Inferno Dragon", "Tornado", "Mighty Miner", "Guards",
        }:
            # Одно место — critical, без зеркала в mid.
            _add(out.critical_interactions, f"Против {_ru(threat)} держи {_ru(answer)}.")


def _danger_cards(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    for threat in opp:
        if is_pure_spell(threat) and threat not in WIN_CONDITIONS:
            continue
        # Только реальные угрозы (WC/tank), не здания-контры вроде Tesla.
        if not (
            threat in WIN_CONDITIONS
            or card_has_role(threat, "win_condition")
            or card_has_role(threat, "tank")
        ):
            continue
        if is_building(threat) or threat in _DEFENSIVE_BUILDINGS:
            continue
        strong, partial = counters_in_deck(threat, user)
        if strong:
            continue
        if partial:
            reason = f"Только слабый ответ ({_ru(partial[0])}) — риск пробить."
        else:
            reason = "Нет счётчика в колоде."
        out.danger_cards.append(DangerCard(
            name=threat,
            name_ru=_ru(threat),
            reason=reason,
        ))
        if len(out.danger_cards) >= 4:
            break


def _phase_from_plans(
    user: list[str],
    opp: list[str],
    user_plan: GamePlan,
    user_arch: str,
    out: TacticalMatchupReport,
) -> None:
    user_wins = _deck_wins(user)
    opp_wins = _deck_wins(opp)
    user_primary = user_wins[0] if user_wins else None
    opp_primary = opp_wins[0] if opp_wins else None
    opp_bld = _deck_def_buildings(opp)
    user_bld = _deck_def_buildings(user)

    if user_primary and user_primary in _BRIDGE_WINS:
        if opp_bld:
            # Не дублируем openings «после траты здания».
            already = any(_mentions_pair(x, user_primary, opp_bld[0]) for x in out.best_openings)
            if not already:
                _add(out.early_game, f"Ранняя игра: не форсируй {_ru(user_primary)} в готовое здание.")
        else:
            _add(out.early_game, f"Ранняя игра: цикл к {_ru(user_primary)} — соперник без здания.")
    if opp_primary and opp_primary in _BRIDGE_WINS and user_bld:
        _add(out.early_game, f"Ранняя защита: держи {_ru(user_bld[0])} против {_ru(opp_primary)}.")
    if user_arch in {"Log Bait", "Fireball Bait"} and _deck_small_spells(opp):
        _add(out.early_game, "Ранний bait: вытяни малый спелл до основной угрозы.")

    if user_primary and user_primary in _BEATDOWN_TANKS:
        _add(out.mid_game, f"Мид: набор {_ru(user_primary)} сзади после выгодной защиты.")
    if opp_primary and opp_primary in _BEATDOWN_TANKS:
        strong, partial = counters_in_deck(opp_primary, user)
        ans = strong or partial
        if ans:
            # Не дублируем critical «держи answer».
            already = any(_mentions_pair(x, ans[0], opp_primary) for x in out.critical_interactions)
            if not already:
                _add(out.mid_game, f"Мид: готовь {_ru(ans[0])} к пушу {_ru(opp_primary)}.")
    if user_plan.core_combinations:
        combo = user_plan.core_combinations[0]
        parts = [p.strip() for p in combo.split(" + ")]
        if len(parts) >= 2 and all(p in user for p in parts[:2]):
            # Не повторять ту же пару, что уже в critical как защита.
            already = any(
                _mentions_pair(x, parts[0], parts[1]) for x in out.critical_interactions
            )
            if not already:
                _add(out.mid_game, f"Ключевая связка мида: {_combo_ru(combo)}.")

    if user_primary and user_primary in _BEATDOWN_TANKS | _SIEGE:
        _add(out.late_game, f"Дабл-эликсир: усиливай давление через {_ru(user_primary)}.")
    if opp_primary and opp_primary in _BEATDOWN_TANKS:
        _add(
            out.late_game,
            f"Дабл-эликсир: {_ru(opp_primary)} набирается быстрее — не отдавай эликсир впустую.",
        )


def _openings_from_cycle(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    if not any(c in user for c in _BRIDGE_WINS):
        return
    win = next(c for c in user if c in _BRIDGE_WINS)
    if _deck_def_buildings(opp):
        return
    cheap = [c for c in user if get_card_elixir(c) <= 2 and not is_pure_spell(c)]
    if cheap:
        _add(
            out.best_openings,
            f"Открытие: {_ru(cheap[0])} → цикл к {_ru(win)} (у соперника нет здания).",
        )
    elif "Ice Spirit" in user:
        _add(out.best_openings, f"Открытие циклом с {_ru('Ice Spirit')} к {_ru(win)}.")


def _pressure_from_plans(
    user: list[str],
    opp: list[str],
    opp_plan: GamePlan,
    out: TacticalMatchupReport,
) -> None:
    for weakness in opp_plan.critical_weaknesses[:3]:
        low = weakness.lower()
        if "воздух" in low:
            from bot.services.card_data import card_is_flying

            air = next((c for c in user if card_is_flying(c)), None)
            if air:
                _add(out.pressure_points, f"Дави воздухом ({_ru(air)}) — у соперника слабая ПВО.")
        if "спам" in low:
            spam = next((c for c in user if is_spam_card(c)), None)
            if spam:
                _add(out.pressure_points, f"Спам ({_ru(spam)}) давит слабость соперника к рою.")
        if "здание" in low:
            # Только если здания реально нет — иначе это дубль Hog/Tesla openings.
            if _deck_def_buildings(opp):
                continue
            tool = next((c for c in user if c in _BRIDGE_WINS | _SIEGE), None)
            if tool:
                _add(out.pressure_points, f"{_ru(tool)} сильнее — у соперника нет здания.")


class TacticalMatchupAnalyzer:
    """Публичный API тактического разбора матчапа."""

    @staticmethod
    def analyze(
        user_deck: list[str],
        opponent_deck: list[str],
        *,
        user_plan: GamePlan | None = None,
        opponent_plan: GamePlan | None = None,
    ) -> TacticalMatchupReport:
        user = list(user_deck)
        opp = list(opponent_deck)
        out = TacticalMatchupReport()

        if len(user) < 8 or len(opp) < 8:
            return out

        user_arch = detect_archetype_from_cards(user)
        opp_arch = detect_archetype_from_cards(opp)
        user_intent = DeckIntentEngine.infer(user, archetype=user_arch)
        opp_intent = DeckIntentEngine.infer(opp, archetype=opp_arch)
        user_plan = user_plan or build_game_plan(user, archetype=user_arch, intent=user_intent)
        opp_plan = opponent_plan or build_game_plan(opp, archetype=opp_arch, intent=opp_intent)

        _spell_hold_rules(user, opp, out)
        _defense_combo_rules(user, opp, out)
        _building_vs_bridge_rules(user, opp, out)
        _bait_rules(user, opp, out)
        _hold_answer_for_win(user, opp, out)
        _danger_cards(user, opp, out)
        _phase_from_plans(user, opp, user_plan, user_arch, out)
        _openings_from_cycle(user, opp, out)
        _pressure_from_plans(user, opp, opp_plan, out)

        return out


def analyze_tactical_matchup(
    user_deck: list[str],
    opponent_deck: list[str],
    *,
    user_plan: GamePlan | None = None,
    opponent_plan: GamePlan | None = None,
) -> TacticalMatchupReport:
    return TacticalMatchupAnalyzer.analyze(
        user_deck,
        opponent_deck,
        user_plan=user_plan,
        opponent_plan=opponent_plan,
    )
