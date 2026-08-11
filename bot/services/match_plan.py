"""MatchPlanBuilder — план игры на конкретный матчап.

Входы: my_deck, enemy_deck, GamePlan обеих сторон, TacticalMatchupAnalyzer.
Без общих советов: каждая строка следует из пересечения составов / тактики.
Одна тема — одно место (дедуп по фазам / avoid / окну атаки).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from bot.services.card_data import WIN_CONDITIONS, card_has_role, get_card_elixir, is_building
from bot.services.card_matchups import counters_in_deck
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_builder.archetype_detect import detect_archetype_from_cards
from bot.services.deck_game_plan import GamePlan, build_game_plan
from bot.services.deck_intent import DeckIntentEngine
from bot.services.spell_hold import FIREBALL_HOLD_PRIORITY, pick_fireball_hold
from bot.services.tactical_matchup import TacticalMatchupAnalyzer, TacticalMatchupReport

_BRIDGE_WINS = frozenset({
    "Hog Rider", "Battle Ram", "Ram Rider", "Royal Hogs", "Wall Breakers",
    "Elite Barbarians", "Goblin Barrel", "Skeleton Barrel", "Goblin Drill",
})
_BEATDOWN = frozenset({
    "Golem", "Lava Hound", "Electro Giant", "Elixir Golem", "Goblin Giant", "Giant",
})
_SIEGE = frozenset({"X-Bow", "Mortar"})
_VALUE_SPELLS = frozenset({
    "Fireball", "Poison", "Lightning", "Rocket", "Earthquake",
})
_SPELL_HOLD: dict[str, tuple[str, ...]] = {
    "Fireball": FIREBALL_HOLD_PRIORITY,
    "Poison": (
        "Graveyard", "Goblin Barrel", "Skeleton Barrel", "Furnace",
        "Goblin Hut", "Barbarian Hut", "Witch", "Night Witch", "Tombstone",
    ),
    "Lightning": (
        "Inferno Tower", "Inferno Dragon", "Sparky", "Three Musketeers",
        "Archer Queen", "Wizard", "Witch", "Electro Wizard", "Musketeer",
    ),
    "Rocket": ("X-Bow", "Mortar", "Sparky", "Three Musketeers", "Elixir Collector"),
    "Earthquake": (
        "X-Bow", "Mortar", "Tesla", "Cannon", "Inferno Tower", "Bomb Tower",
        "Goblin Cage", "Tombstone",
    ),
}
_DEF_BUILDINGS = frozenset({
    "Cannon", "Tesla", "Inferno Tower", "Bomb Tower", "Goblin Cage",
    "Tombstone", "Goblin Hut", "Barbarian Hut",
})


def _ru(card: str) -> str:
    return card_name_ru(card) or card


def _wins(deck: list[str]) -> list[str]:
    return [c for c in deck if c in WIN_CONDITIONS or card_has_role(c, "win_condition")]


def _primary_win(deck: list[str]) -> str | None:
    wins = _wins(deck)
    if not wins:
        return None
    return sorted(wins, key=lambda c: (get_card_elixir(c), c))[0]


def _buildings(deck: list[str]) -> list[str]:
    return [c for c in deck if c in _DEF_BUILDINGS or is_building(c)]


def _topic_key(text: str) -> frozenset[str]:
    """Грубый ключ темы для дедупа перефразов."""
    stop = {
        "после", "траты", "готовое", "лучше", "пускать", "пускай", "не", "в", "на",
        "или", "когда", "здание", "кулдауне", "давление", "при", "отсутствии",
        "у", "соперника", "проигрышный", "обмен", "финиш", "цикл", "к",
        "моменты", "без", "ранний", "игра", "мид", "держи", "против", "ответ",
        "ключевая", "защита", "сильная", "от", "связка", "набирай", "выгодной",
        "игнорируй", "только", "слабый", "риск", "пробить", "окно", "атаки",
        "берег", "береги", "выше", "ценность", "конце", "под",
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


def _overlaps(a: frozenset[str], b: frozenset[str]) -> bool:
    """Дубль, если ≥2 значимых токена совпали (одна карта ≠ одна тема)."""
    if not a or not b:
        return False
    return len(a & b) >= 2


def _add_unique_topic(
    bucket: list[str],
    line: str,
    seen: list[frozenset[str]],
    *,
    limit: int = 5,
) -> None:
    if not line or len(bucket) >= limit:
        return
    key = _topic_key(line)
    if any(_overlaps(key, s) for s in seen):
        return
    if line in bucket:
        return
    bucket.append(line)
    seen.append(key)


@dataclass
class SaveCard:
    name: str
    name_ru: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MatchGamePlanPhases:
    phase_1: list[str] = field(default_factory=list)
    phase_2: list[str] = field(default_factory=list)
    phase_3: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "phase_1": list(self.phase_1),
            "phase_2": list(self.phase_2),
            "phase_3": list(self.phase_3),
        }

    def has_content(self) -> bool:
        return bool(self.phase_1 or self.phase_2 or self.phase_3)


@dataclass
class MatchPlanReport:
    game_plan: MatchGamePlanPhases = field(default_factory=MatchGamePlanPhases)
    avoid: list[str] = field(default_factory=list)
    save_cards: list[SaveCard] = field(default_factory=list)
    win_condition_window: str = ""

    def to_dict(self) -> dict:
        return {
            "game_plan": self.game_plan.to_dict(),
            "avoid": list(self.avoid),
            "save_cards": [s.to_dict() for s in self.save_cards],
            "win_condition_window": self.win_condition_window,
        }

    def has_content(self) -> bool:
        return bool(
            self.game_plan.has_content()
            or self.avoid
            or self.save_cards
            or self.win_condition_window
        )


def _save_card(out: list[SaveCard], name: str, reason: str, *, limit: int = 5) -> None:
    if any(s.name == name for s in out) or len(out) >= limit:
        return
    out.append(SaveCard(name=name, name_ru=_ru(name), reason=reason))


def _build_save_cards(my: list[str], enemy: list[str]) -> list[SaveCard]:
    """Карты для руки — отдельный UI, без текстовых дублей фаз."""
    out: list[SaveCard] = []

    if "Fireball" in my:
        focus, reason = pick_fireball_hold(my, enemy)
        if focus:
            _save_card(out, "Fireball", reason)

    for spell, targets in _SPELL_HOLD.items():
        if spell == "Fireball" or spell not in my:
            continue
        present = [t for t in targets if t in enemy]
        if present:
            _save_card(out, spell, f"Держи до появления {_ru(present[0])}.")

    for threat in _wins(enemy)[:2]:
        strong, partial = counters_in_deck(threat, my)
        answers = strong or partial
        if not answers:
            continue
        answer = answers[0]
        if (
            is_building(answer)
            or answer in _DEF_BUILDINGS
            or answer in _VALUE_SPELLS
            or card_has_role(answer, "anti_tank")
            or answer in {"Tornado", "Mighty Miner", "Inferno Dragon", "Guards"}
        ):
            _save_card(out, answer, f"Ответ на {_ru(threat)}.")

    if "Tornado" in my and any(
        c in my for c in ("Executioner", "Wizard", "Baby Dragon", "Bowler", "Valkyrie")
    ):
        if any(card_has_role(c, "swarm") for c in enemy) or any(
            c in enemy for c in ("Balloon", "Graveyard", "Goblin Barrel", "Minion Horde")
        ):
            _save_card(out, "Tornado", "Ключ защитной связки в этом матчапе.")

    return out


def _build_avoid(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
    my_plan: GamePlan,
    seen: list[frozenset[str]],
) -> list[str]:
    avoid: list[str] = []

    for line in tactical.worst_mistakes:
        _add_unique_topic(avoid, line, seen)

    enemy_win = _primary_win(enemy)
    if enemy_win and enemy_win in _BEATDOWN:
        _add_unique_topic(
            avoid,
            f"Не отдавай эликсир впустую перед пушем {_ru(enemy_win)}.",
            seen,
        )

    if "Goblin Barrel" in enemy:
        small = next(
            (
                c for c in my
                if c in {"The Log", "Zap", "Arrows", "Barbarian Barrel", "Giant Snowball"}
                or card_has_role(c, "small_spell")
            ),
            None,
        )
        bait_else = [
            c for c in enemy
            if c in {"Princess", "Goblin Gang", "Dart Goblin", "Skeleton Barrel"}
        ]
        if small and bait_else:
            _add_unique_topic(
                avoid,
                f"Не трать {_ru(small)} на {_ru(bait_else[0])} до {_ru('Goblin Barrel')}.",
                seen,
            )

    for danger in tactical.danger_cards[:2]:
        _add_unique_topic(
            avoid,
            f"Не игнорируй {_ru(danger.name)} — {danger.reason}",
            seen,
        )

    for w in my_plan.critical_weaknesses[:2]:
        if "воздух" in w.lower() and any(
            c in enemy for c in ("Balloon", "Lava Hound", "Minion Horde", "Flying Machine")
        ):
            air = next(
                c for c in enemy
                if c in ("Balloon", "Lava Hound", "Minion Horde", "Flying Machine")
            )
            _add_unique_topic(avoid, f"Не оставайся без ответа на {_ru(air)}.", seen)
        if "здание" in w.lower() and any(c in enemy for c in _BRIDGE_WINS | _SIEGE):
            tool = next(c for c in enemy if c in _BRIDGE_WINS | _SIEGE)
            _add_unique_topic(avoid, f"Без здания не зевай {_ru(tool)}.", seen)

    return avoid


def _win_condition_window(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
    my_plan: GamePlan,
) -> str:
    my_win = _primary_win(my)
    if not my_win:
        return ""

    enemy_bld = _buildings(enemy)
    enemy_def = [c for c in enemy if c in _DEF_BUILDINGS]
    if my_win in _BRIDGE_WINS and enemy_def:
        return (
            f"Окно для {_ru(my_win)}: после того как {_ru(enemy_def[0])} потрачен "
            f"или на кулдауне — иначе атака закрывается дёшево."
        )
    if my_win in _BRIDGE_WINS and not enemy_def:
        return (
            f"Окно для {_ru(my_win)}: с первых минут, как только цикл собран — "
            f"у соперника нет здания для дешёвого стопа."
        )
    if my_win in _BEATDOWN:
        return (
            f"Окно для {_ru(my_win)}: после выгодной защиты, набор сзади "
            f"уже в плюсе по эликсиру."
        )
    if my_win in _SIEGE:
        return (
            f"Окно для {_ru(my_win)}: когда соперник в минусе или его контрпуш отбит — "
            f"иначе осаду сносят бесплатно."
        )
    if my_win == "Graveyard":
        spell = next((c for c in my if c in {"Poison", "Freeze", "Barbarian Barrel"}), None)
        if spell:
            return (
                f"Окно для {_ru(my_win)}: в паре с {_ru(spell)} после стопа пуша — "
                f"так кладбище успевает нанести урон."
            )
        return f"Окно для {_ru(my_win)}: после стопа пуша, на танк или в плюсе по эликсиру."
    if my_win == "Goblin Barrel":
        small = next(
            (c for c in enemy if c in {"The Log", "Zap", "Arrows", "Barbarian Barrel"}),
            None,
        )
        if small:
            return (
                f"Окно для {_ru(my_win)}: после того как {_ru(small)} ушёл на bait — "
                f"у соперника нет дешёвого сброса бочки, урон по башне чище."
            )
        return f"Окно для {_ru(my_win)}: в сплите со второй bait-угрозой."

    for line in tactical.best_openings:
        if _ru(my_win) in line or my_win in line:
            return line
    if my_plan.when_to_attack and my_win in my:
        return f"{_ru(my_win)}: {my_plan.when_to_attack}"
    return ""


def _phase_1(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
    my_win: str | None,
    seen: list[frozenset[str]],
) -> list[str]:
    phase: list[str] = []
    for line in tactical.early_game[:3]:
        _add_unique_topic(phase, line, seen)
    if not phase:
        for line in tactical.best_openings[:2]:
            _add_unique_topic(phase, line, seen)

    enemy_win = _primary_win(enemy)
    my_bld = _buildings(my)
    if enemy_win and enemy_win in _BRIDGE_WINS and my_bld:
        _add_unique_topic(
            phase,
            f"В старте держи {_ru(my_bld[0])} готовым к {_ru(enemy_win)}.",
            seen,
        )
    if my_win and my_win in _BEATDOWN:
        _add_unique_topic(
            phase,
            f"Ранняя игра — дешёвые обмены, не форсируй {_ru(my_win)}.",
            seen,
        )
    if not phase and my_win:
        cheap = [c for c in my if get_card_elixir(c) <= 2 and c != my_win]
        if cheap:
            _add_unique_topic(
                phase,
                f"Открой циклом через {_ru(cheap[0])}, готовь {_ru(my_win)}.",
                seen,
            )
    return phase


def _phase_2(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
    my_plan: GamePlan,
    enemy_plan: GamePlan,
    my_win: str | None,
    seen: list[frozenset[str]],
) -> list[str]:
    phase: list[str] = []
    # Только mid + уникальный pressure. Critical остаётся в тактике / save_cards.
    for line in tactical.mid_game[:4]:
        _add_unique_topic(phase, line, seen)
    for line in tactical.pressure_points[:2]:
        _add_unique_topic(phase, line, seen)

    for w in enemy_plan.critical_weaknesses[:2]:
        low = w.lower()
        if "воздух" in low:
            from bot.services.card_data import card_is_flying

            air = next((c for c in my if card_is_flying(c)), None)
            if air:
                _add_unique_topic(
                    phase,
                    f"Преимущество: дави {_ru(air)} — у соперника слабая ПВО, "
                    f"воздушный урон проходит в башню.",
                    seen,
                )
        if "здание" in low and my_win and my_win in _BRIDGE_WINS | _SIEGE:
            if any(c in _DEF_BUILDINGS for c in enemy):
                continue
            _add_unique_topic(
                phase,
                f"Преимущество: {_ru(my_win)} без здания у соперника — "
                f"дешёвой защиты bridge-атаки нет.",
                seen,
            )
        if "спам" in low:
            spam = next((c for c in my if card_has_role(c, "swarm")), None)
            if spam:
                _add_unique_topic(
                    phase,
                    f"Преимущество: {_ru(spam)} против слабого anti-swarm — "
                    f"дешёвое давление наносит урон.",
                    seen,
                )

    if my_plan.core_combinations:
        combo = my_plan.core_combinations[0]
        parts = [p.strip() for p in combo.split(" + ")]
        if len(parts) >= 2 and all(p in my for p in parts[:2]):
            left, right = _ru(parts[0]), _ru(parts[1])
            _add_unique_topic(
                phase,
                f"Набирай связку {left} + {right} после выгодной защиты.",
                seen,
            )
    return phase


def _phase_3(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
    my_win: str | None,
    seen: list[frozenset[str]],
) -> list[str]:
    phase: list[str] = []
    for line in tactical.late_game[:3]:
        _add_unique_topic(phase, line, seen)

    if my_win and my_win in _BEATDOWN | _SIEGE:
        _add_unique_topic(
            phase,
            f"Дабл-эликсир: закрывай через усиленный пуш {_ru(my_win)}.",
            seen,
        )
    elif my_win and my_win in _BRIDGE_WINS and not _buildings(enemy):
        _add_unique_topic(
            phase,
            f"Финиш: непрерывный цикл {_ru(my_win)} в дабл-эликсире.",
            seen,
        )

    for spell in _VALUE_SPELLS:
        if spell not in my:
            continue
        targets = [t for t in _SPELL_HOLD.get(spell, ()) if t in enemy]
        if targets:
            _add_unique_topic(
                phase,
                f"В конце ценность {_ru(spell)} выше — береги под {_ru(targets[0])}.",
                seen,
            )
            break
    return phase


class MatchPlanBuilder:
    """Строит уникальный план матчапа из колод, GamePlan и тактики."""

    @staticmethod
    def build(
        my_deck: list[str],
        enemy_deck: list[str],
        *,
        my_plan: GamePlan | None = None,
        enemy_plan: GamePlan | None = None,
        tactical: TacticalMatchupReport | None = None,
    ) -> MatchPlanReport:
        if len(my_deck) < 8 or len(enemy_deck) < 8:
            return MatchPlanReport()

        my = list(my_deck)
        enemy = list(enemy_deck)

        my_arch = detect_archetype_from_cards(my)
        enemy_arch = detect_archetype_from_cards(enemy)
        my_intent = DeckIntentEngine.infer(my, archetype=my_arch)
        enemy_intent = DeckIntentEngine.infer(enemy, archetype=enemy_arch)
        my_plan = my_plan or build_game_plan(my, archetype=my_arch, intent=my_intent)
        enemy_plan = enemy_plan or build_game_plan(
            enemy, archetype=enemy_arch, intent=enemy_intent
        )
        tactical = tactical or TacticalMatchupAnalyzer.analyze(
            my, enemy, user_plan=my_plan, opponent_plan=enemy_plan
        )

        my_win = _primary_win(my)
        window = _win_condition_window(my, enemy, tactical, my_plan)

        # Темы тактики/окна не повторяем в фазах плана.
        seen: list[frozenset[str]] = []
        if window:
            seen.append(_topic_key(window))
        for line in tactical.critical_interactions:
            seen.append(_topic_key(line))
        for line in tactical.best_openings:
            seen.append(_topic_key(line))

        phase_1 = _phase_1(my, enemy, tactical, my_win, seen)
        phase_2 = _phase_2(my, enemy, tactical, my_plan, enemy_plan, my_win, seen)
        phase_3 = _phase_3(my, enemy, tactical, my_win, seen)
        # Avoid: worst_mistakes ок, но без перекрытия с окном/фазами.
        avoid = _build_avoid(my, enemy, tactical, my_plan, seen)

        return MatchPlanReport(
            game_plan=MatchGamePlanPhases(
                phase_1=phase_1,
                phase_2=phase_2,
                phase_3=phase_3,
            ),
            avoid=avoid,
            save_cards=_build_save_cards(my, enemy),
            win_condition_window=window,
        )


def build_match_plan(
    my_deck: list[str],
    enemy_deck: list[str],
    *,
    my_plan: GamePlan | None = None,
    enemy_plan: GamePlan | None = None,
    tactical: TacticalMatchupReport | None = None,
) -> MatchPlanReport:
    return MatchPlanBuilder.build(
        my_deck,
        enemy_deck,
        my_plan=my_plan,
        enemy_plan=enemy_plan,
        tactical=tactical,
    )
