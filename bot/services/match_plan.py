"""MatchPlanBuilder — план игры на конкретный матчап.

Входы: my_deck, enemy_deck, GamePlan обеих сторон, TacticalMatchupAnalyzer.
Без общих советов: каждая строка следует из пересечения составов / тактики.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from bot.services.card_data import WIN_CONDITIONS, card_has_role, get_card_elixir, is_building
from bot.services.card_matchups import counters_in_deck
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_builder.archetype_detect import detect_archetype_from_cards
from bot.services.deck_game_plan import GamePlan, build_game_plan
from bot.services.deck_intent import DeckIntentEngine
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
    "Fireball": (
        "Flying Machine", "Three Musketeers", "Archer Queen", "Firecracker",
        "Musketeer", "Wizard", "Witch", "Magic Archer", "Dart Goblin",
        "Mother Witch", "Zappies",
    ),
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


def _add(bucket: list[str], line: str, *, limit: int = 5) -> None:
    if line and line not in bucket and len(bucket) < limit:
        bucket.append(line)


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


def _build_save_cards(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
) -> list[SaveCard]:
    out: list[SaveCard] = []

    for spell, targets in _SPELL_HOLD.items():
        if spell not in my:
            continue
        present = [t for t in targets if t in enemy]
        if not present:
            continue
        focus = present[0]
        _save_card(out, spell, f"Держи до появления {_ru(focus)}.")

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
            or answer in {"Tornado", "Mighty Miner", "Inferno Dragon"}
        ):
            _save_card(out, answer, f"Ответ на {_ru(threat)}.")

    # Защитные комбо: Tornado / splash
    if "Tornado" in my and any(
        c in my for c in ("Executioner", "Wizard", "Baby Dragon", "Bowler", "Valkyrie")
    ):
        if any(card_has_role(c, "swarm") for c in enemy) or any(
            c in enemy for c in ("Balloon", "Graveyard", "Goblin Barrel", "Minion Horde")
        ):
            _save_card(out, "Tornado", "Ключ защитной связки в этом матчапе.")

    # Из тактики: «держи X»
    for line in tactical.critical_interactions + tactical.mid_game:
        if "держи" not in line.lower():
            continue
        for card in my:
            if _ru(card) in line and card not in {s.name for s in out}:
                _save_card(out, card, line)
                break

    return out


def _build_avoid(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
    my_plan: GamePlan,
    enemy_plan: GamePlan,
) -> list[str]:
    avoid: list[str] = []
    for line in tactical.worst_mistakes:
        _add(avoid, line)

    my_win = _primary_win(my)
    enemy_bld = _buildings(enemy)
    if my_win and my_win in _BRIDGE_WINS and enemy_bld:
        _add(avoid, f"Не пускай {_ru(my_win)} в готовое {_ru(enemy_bld[0])}.")

    enemy_win = _primary_win(enemy)
    if enemy_win and enemy_win in _BEATDOWN:
        _add(avoid, f"Не отдавай эликсир впустую перед пушем {_ru(enemy_win)}.")

    # Bait: не тратить малый спелл на первую bait-угрозу, если есть бочка
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
            _add(
                avoid,
                f"Не трать {_ru(small)} на {_ru(bait_else[0])} до {_ru('Goblin Barrel')}.",
            )

    for danger in tactical.danger_cards[:2]:
        _add(avoid, f"Не игнорируй {_ru(danger.name)} — {danger.reason}")

    # Слабости нашего плана, которые враг может наказать
    for w in my_plan.critical_weaknesses[:2]:
        if "воздух" in w.lower() and any(
            c in enemy for c in ("Balloon", "Lava Hound", "Minion Horde", "Flying Machine")
        ):
            air = next(
                c for c in enemy
                if c in ("Balloon", "Lava Hound", "Minion Horde", "Flying Machine")
            )
            _add(avoid, f"Не оставайся без ответа на {_ru(air)}.")
        if "здание" in w.lower() and any(c in enemy for c in _BRIDGE_WINS | _SIEGE):
            tool = next(c for c in enemy if c in _BRIDGE_WINS | _SIEGE)
            _add(avoid, f"Без здания не зевай {_ru(tool)}.")

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
    if my_win in _BRIDGE_WINS and enemy_bld:
        return f"{_ru(my_win)} — после траты {_ru(enemy_bld[0])} или когда здание на кулдауне."

    if my_win in _BRIDGE_WINS and not enemy_bld:
        return f"{_ru(my_win)} — с первых минут, как только цикл собран (у соперника нет здания)."

    if my_win in _BEATDOWN:
        return f"{_ru(my_win)} — после выгодной защиты, набор сзади в плюсе по эликсиру."

    if my_win in _SIEGE:
        return f"{_ru(my_win)} — когда соперник в минусе или его контрпуш отбит."

    if my_win == "Graveyard":
        spell = next((c for c in my if c in {"Poison", "Freeze", "Barbarian Barrel"}), None)
        if spell:
            return f"{_ru(my_win)} — в паре с {_ru(spell)} после стопа пуша соперника."
        return f"{_ru(my_win)} — после стопа пуша, на танк или в плюсе."

    if my_win == "Goblin Barrel":
        small = next(
            (c for c in enemy if c in {"The Log", "Zap", "Arrows", "Barbarian Barrel"}),
            None,
        )
        if small:
            return f"{_ru(my_win)} — после траты {_ru(small)} соперника на bait."
        return f"{_ru(my_win)} — в сплите со второй bait-угрозой."

    # Из тактических openings
    for line in tactical.best_openings:
        if _ru(my_win) in line or my_win in line:
            return line

    # Только если when_to_attack опирается на реальный primary в колоде
    if my_plan.when_to_attack and my_win in my:
        return f"{_ru(my_win)}: {my_plan.when_to_attack}"

    return f"Атакуй {_ru(my_win)}, когда ответ соперника потрачен или ты в плюсе."


def _phase_1(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
    my_win: str | None,
) -> list[str]:
    phase: list[str] = []
    for line in tactical.best_openings[:2]:
        _add(phase, line)
    for line in tactical.early_game[:3]:
        _add(phase, line)

    enemy_win = _primary_win(enemy)
    my_bld = _buildings(my)
    if enemy_win and enemy_win in _BRIDGE_WINS and my_bld:
        _add(phase, f"В старте держи {_ru(my_bld[0])} готовым к {_ru(enemy_win)}.")

    if my_win and my_win in _BEATDOWN:
        _add(phase, f"Ранняя игра — дешёвые обмены, не форсируй {_ru(my_win)}.")

    if not phase and my_win:
        cheap = [c for c in my if get_card_elixir(c) <= 2 and c != my_win]
        if cheap:
            _add(phase, f"Открой циклом через {_ru(cheap[0])}, готовь {_ru(my_win)}.")

    return phase


def _phase_2(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
    my_plan: GamePlan,
    enemy_plan: GamePlan,
    my_win: str | None,
) -> list[str]:
    phase: list[str] = []
    for line in tactical.mid_game[:3]:
        _add(phase, line)
    for line in tactical.pressure_points[:2]:
        _add(phase, line)
    for line in tactical.critical_interactions[:2]:
        if line not in phase:
            # Только actionable mid tips
            if any(k in line.lower() for k in ("держи", "защита", "после", "дави", "связка")):
                _add(phase, line)

    for w in enemy_plan.critical_weaknesses[:2]:
        low = w.lower()
        if "воздух" in low:
            air = next(
                (
                    c for c in my
                    if card_has_role(c, "air")
                    or c in {"Balloon", "Minions", "Flying Machine", "Lava Hound"}
                ),
                None,
            )
            if air:
                _add(phase, f"Преимущество: дави {_ru(air)} в слабую ПВО.")
        if "здание" in low and my_win and my_win in _BRIDGE_WINS | _SIEGE:
            _add(phase, f"Преимущество: {_ru(my_win)} без здания у соперника.")
        if "спам" in low:
            spam = next((c for c in my if card_has_role(c, "swarm")), None)
            if spam:
                _add(phase, f"Преимущество: {_ru(spam)} против слабого anti-swarm.")

    if my_plan.core_combinations:
        combo = my_plan.core_combinations[0]
        parts = [p.strip() for p in combo.split(" + ")]
        if len(parts) >= 2 and all(p in my for p in parts[:2]):
            left, right = _ru(parts[0]), _ru(parts[1])
            _add(phase, f"Набирай связку {left} + {right} после выгодной защиты.")

    return phase


def _phase_3(
    my: list[str],
    enemy: list[str],
    tactical: TacticalMatchupReport,
    my_win: str | None,
) -> list[str]:
    phase: list[str] = []
    for line in tactical.late_game[:3]:
        _add(phase, line)

    if my_win and my_win in _BEATDOWN | _SIEGE:
        _add(phase, f"Дабл-эликсир: закрывай через усиленный пуш {_ru(my_win)}.")
    elif my_win and my_win in _BRIDGE_WINS:
        enemy_bld = _buildings(enemy)
        if enemy_bld:
            _add(
                phase,
                f"Финиш: цикл к {_ru(my_win)} в моменты без {_ru(enemy_bld[0])}.",
            )
        else:
            _add(phase, f"Финиш: непрерывный цикл {_ru(my_win)} в дабл-эликсире.")

    for spell in _VALUE_SPELLS:
        if spell not in my:
            continue
        targets = [t for t in _SPELL_HOLD.get(spell, ()) if t in enemy]
        if targets:
            _add(phase, f"В конце ценность {_ru(spell)} выше — береги под {_ru(targets[0])}.")
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
        report = MatchPlanReport(
            game_plan=MatchGamePlanPhases(
                phase_1=_phase_1(my, enemy, tactical, my_win),
                phase_2=_phase_2(my, enemy, tactical, my_plan, enemy_plan, my_win),
                phase_3=_phase_3(my, enemy, tactical, my_win),
            ),
            avoid=_build_avoid(my, enemy, tactical, my_plan, enemy_plan),
            save_cards=_build_save_cards(my, enemy, tactical),
            win_condition_window=_win_condition_window(my, enemy, tactical, my_plan),
        )
        return report


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
