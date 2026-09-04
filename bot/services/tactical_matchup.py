"""TacticalMatchupAnalyzer — тактический разбор пары колод.

Только факты из состава A/B: роли, win-conditions, синергии, контры,
архетипы, GamePlan. Никакого урона, случайных эвристик и шаблонных советов
без предпосылок в обеих колодах.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from bot.services.card_data import (
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


def _ru_list(cards: list[str], *, limit: int = 3) -> str:
    return ", ".join(_ru(c) for c in cards[:limit])


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
    return card_counters_target(spell, target) in {"strong", "partial"}


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


def _add(bucket: list[str], line: str, *, limit: int = 4) -> None:
    """Append a unique insight; keep lists short (quality over filler)."""
    if line and line not in bucket and len(bucket) < limit:
        bucket.append(line)


def _insight_tokens(text: str) -> frozenset[str]:
    stop = {
        "после", "траты", "готовое", "лучше", "пускать", "пускай", "не", "в", "на",
        "или", "когда", "здание", "у", "соперника", "проигрышный", "обмен", "для",
        "атака", "атаку", "проходит", "дешевле", "и", "как", "только", "чем",
        "дождись", "пока", "уйдёт", "с", "цикла", "сохраняет", "инициативу",
        "меньше", "ресурса", "защиту", "защиты", "чище", "запускать", "того",
        "ранний", "потеря", "ценности", "появление", "появления",
    }
    raw = (
        text.lower()
        .replace("—", " ")
        .replace("-", " ")
        .replace(".", " ")
        .replace(",", " ")
        .replace(":", " ")
        .replace("(", " ")
        .replace(")", " ")
    )
    return frozenset(t for t in raw.split() if len(t) > 2 and t not in stop)


def _insights_overlap(a: str, b: str) -> bool:
    ta, tb = _insight_tokens(a), _insight_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) >= 2


def _dedupe_within_bucket(bucket: list[str]) -> None:
    """Drop near-duplicates inside one list (exact dupes already blocked by _add)."""
    kept: list[str] = []
    filtered: list[str] = []
    for line in bucket:
        if any(_insights_overlap(line, prev) for prev in kept):
            continue
        filtered.append(line)
        kept.append(line)
    bucket[:] = filtered


def _dedupe_cross_buckets(out: TacticalMatchupReport) -> None:
    """Prune phase/pressure tips that restate openings, mistakes, or critical.

    Openings ↔ mistakes ↔ critical for the same card pair are intentional
    inverses (what to do / what not to do / what to hold) and must all survive.
    """
    primary = (out.best_openings, out.worst_mistakes, out.critical_interactions)
    secondary = (out.pressure_points, out.early_game, out.mid_game, out.late_game)

    for bucket in primary:
        _dedupe_within_bucket(bucket)

    anchors = (
        list(out.best_openings)
        + list(out.worst_mistakes)
        + list(out.critical_interactions)
    )
    for bucket in secondary:
        _dedupe_within_bucket(bucket)
        bucket[:] = [
            line
            for line in bucket
            if not any(_insights_overlap(line, a) for a in anchors)
        ]


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
            _add(
                out.critical_interactions,
                f"Придержи {_ru('Fireball')}: {reason} — так ты не сжигаешь ценный спелл впустую.",
            )
            _add(
                out.worst_mistakes,
                f"Ранний {_ru('Fireball')} до {_ru(focus)} сжигает ответ: "
                f"соперник потом продавливает {_ru(focus)} без твоего счётчика.",
            )

    for spell, targets in _SPELL_HOLD_TARGETS.items():
        if spell == "Fireball" or spell not in user:
            continue
        valid = [t for t in targets if t in opp and _spell_answers_target(spell, t)]
        if not valid:
            continue
        focus = valid[0]
        _add(
            out.critical_interactions,
            f"Придержи {_ru(spell)} до {_ru(focus)}: это главный выгодный размен спелла в матчапе.",
        )
        _add(
            out.worst_mistakes,
            f"Тратить {_ru(spell)} до {_ru(focus)} — потеря ценности: "
            f"потом нечем закрыть ключевую карту соперника.",
        )
        if focus == "Graveyard" and spell == "Poison":
            _add(
                out.late_game,
                f"В дабл-эликсире {_ru(focus)} опаснее — держи {_ru(spell)} в руке к пушу.",
            )


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
    """Bridge win vs real defensive buildings only (not Elixir Collector)."""
    opp_def = [c for c in opp if c in _DEFENSIVE_BUILDINGS]
    has_pump = "Elixir Collector" in opp

    for win in (c for c in user if c in _BRIDGE_WINS):
        if opp_def:
            bld = opp_def[0]
            _add(
                out.best_openings,
                f"{_ru(win)} лучше запускать после того, как {_ru(bld)} потрачен: "
                f"у соперника меньше дешёвой защиты, и атака проходит чище.",
            )
            _add(
                out.worst_mistakes,
                f"{_ru(win)} в готовую {_ru(bld)} отдаёт выгодный размен сопернику: "
                f"атака закрывается дёшево, инициатива уходит к нему. "
                f"Дождись, пока {_ru(bld)} уйдёт с цикла.",
            )
        elif has_pump:
            # Pump is not a defensive stop — advise on elixir timing, not "into collector".
            _add(
                out.best_openings,
                f"После постройки {_ru('Elixir Collector')} соперник в минусе по эликсиру — "
                f"окно для {_ru(win)}, пока они не накопят ответ.",
            )


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
        f"Когда {_ru(spell)} соперника потрачен на {_ru(primary)}, "
        f"дави {_ru(secondary)}: у них нет дешёвого ответа на вторую bait-угрозу.",
    )


def _hold_answer_for_win(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    for threat in _deck_wins(opp):
        strong, partial = counters_in_deck(threat, user)
        answers = strong or partial
        if not answers:
            continue
        if threat == "Graveyard" and "Poison" in user:
            _add(
                out.critical_interactions,
                f"Против {_ru(threat)} держи {_ru('Poison')}: "
                f"без спелла кладбище наносит урон по башне.",
            )
            continue
        answer = answers[0]
        if is_building(answer) or answer in _DEFENSIVE_BUILDINGS or card_has_role(answer, "anti_tank") or answer in {
            "Inferno Dragon", "Tornado", "Mighty Miner", "Guards",
        }:
            _add(
                out.critical_interactions,
                f"Против {_ru(threat)} держи {_ru(answer)}: "
                f"это основной стоп win-condition в матчапе.",
            )


def _danger_cards(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    # Хрупкий цикл / воздух — не считаем «ответом» на даш-чемпионов и танки.
    soft = frozenset({
        "Ice Golem", "Ice Spirit", "Skeletons", "Electro Spirit", "Heal Spirit",
        "Fire Spirit", "Bats", "Minions",
    })
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
        strong = [c for c in strong if c not in soft]
        partial = [c for c in partial if c not in soft]
        if strong:
            continue
        if partial:
            reason = f"Только слабый ответ ({_ru_list(partial)}) — риск пробить."
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
            # Не дублируем openings про здание.
            already = any(_mentions_pair(x, user_primary, opp_bld[0]) for x in out.best_openings)
            if not already and opp_bld[0] in _DEFENSIVE_BUILDINGS:
                _add(
                    out.early_game,
                    f"В старте не форсируй {_ru(user_primary)} в готовую {_ru(opp_bld[0])}: "
                    f"соперник закрывает атаку дёшево.",
                )
        else:
            _add(
                out.early_game,
                f"Ранний цикл к {_ru(user_primary)}: у соперника нет здания — "
                f"давление проходит дешевле.",
            )
    if opp_primary and opp_primary in _BRIDGE_WINS and user_bld:
        hold = next((b for b in user_bld if b in _DEFENSIVE_BUILDINGS), user_bld[0])
        _add(
            out.early_game,
            f"Ранняя защита: держи {_ru(hold)} к {_ru(opp_primary)}, "
            f"иначе bridge-атака проходит без ответа.",
        )
    if user_arch in {"Log Bait", "Fireball Bait"} and _deck_small_spells(opp):
        _add(
            out.early_game,
            "Ранний bait: сначала вытяни малый спелл соперника, потом основную угрозу.",
        )

    if user_primary and user_primary in _BEATDOWN_TANKS:
        _add(
            out.mid_game,
            f"Мид: набирай {_ru(user_primary)} сзади после выгодной защиты — "
            f"так пуш идёт уже в плюсе по эликсиру.",
        )
    if opp_primary and opp_primary in _BEATDOWN_TANKS:
        strong, partial = counters_in_deck(opp_primary, user)
        ans = strong or partial
        if ans:
            already = any(_mentions_pair(x, ans[0], opp_primary) for x in out.critical_interactions)
            if not already:
                _add(
                    out.mid_game,
                    f"Мид: готовь {_ru(ans[0])} к пушу {_ru(opp_primary)} — "
                    f"без ответа танк доходит до башни.",
                )
    if user_plan.core_combinations:
        combo = user_plan.core_combinations[0]
        parts = [p.strip() for p in combo.split(" + ")]
        if len(parts) >= 2 and all(p in user for p in parts[:2]):
            already = any(
                _mentions_pair(x, parts[0], parts[1]) for x in out.critical_interactions
            )
            if not already:
                _add(out.mid_game, f"Ключевая связка мида: {_combo_ru(combo)}.")

    if user_primary and user_primary in _BEATDOWN_TANKS | _SIEGE:
        _add(
            out.late_game,
            f"Дабл-эликсир: усиливай давление через {_ru(user_primary)} — "
            f"темп выше, ответы соперника дороже.",
        )
    if opp_primary and opp_primary in _BEATDOWN_TANKS:
        _add(
            out.late_game,
            f"Дабл-эликсир: {_ru(opp_primary)} набирается быстрее — "
            f"не отдавай эликсир впустую до стопа пуша.",
        )


def _openings_from_cycle(user: list[str], opp: list[str], out: TacticalMatchupReport) -> None:
    if not any(c in user for c in _BRIDGE_WINS):
        return
    win = next(c for c in user if c in _BRIDGE_WINS)
    if any(c in _DEFENSIVE_BUILDINGS for c in opp):
        return
    cheap = [c for c in user if get_card_elixir(c) <= 2 and not is_pure_spell(c)]
    if cheap:
        _add(
            out.best_openings,
            f"Открытие: {_ru(cheap[0])} → цикл к {_ru(win)} — "
            f"у соперника нет здания, атака дешевле в ответе.",
        )
    elif "Ice Spirit" in user:
        _add(
            out.best_openings,
            f"Открытие циклом с {_ru('Ice Spirit')} к {_ru(win)} — "
            f"быстрый вход, пока соперник без здания.",
        )


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
                _add(
                    out.pressure_points,
                    f"Дави {_ru(air)}: у соперника слабая ПВО — воздушный урон проходит в башню.",
                )
        if "спам" in low:
            spam = next((c for c in user if is_spam_card(c)), None)
            if spam:
                _add(
                    out.pressure_points,
                    f"Дави {_ru(spam)}: соперник слабо чистит рой — дешёвое давление наносит урон.",
                )
        if "здание" in low:
            if any(c in _DEFENSIVE_BUILDINGS for c in opp):
                continue
            tool = next((c for c in user if c in _BRIDGE_WINS | _SIEGE), None)
            if tool:
                _add(
                    out.pressure_points,
                    f"{_ru(tool)} сильнее обычного: у соперника нет здания — "
                    f"дешёвой защиты bridge-атаки нет.",
                )


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
        _dedupe_cross_buckets(out)

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
