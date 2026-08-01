"""Приоритет hold больших спеллов по целям в колоде соперника."""

from __future__ import annotations

from bot.services.card_matchups import counters_in_deck
from bot.services.card_names_ru import card_name_ru

# Порядок = приоритет: раньше = важнее держать спелл именно на эту карту.
FIREBALL_HOLD_PRIORITY: tuple[str, ...] = (
    # Максимальная ценность
    "Three Musketeers",
    "Archer Queen",
    # Паки / bait, которые лучше всего чистит именно Fireball
    "Barbarians",
    "Elite Barbarians",
    "Royal Hogs",
    "Minion Horde",
    "Furnace",
    "Goblin Hut",
    "Barbarian Hut",
    # Воздух / mid-value
    "Flying Machine",
    "Firecracker",
    "Zappies",
    "Mother Witch",
    # Саппорт — часто есть альтернативный ответ
    "Witch",
    "Wizard",
    "Musketeer",
    "Magic Archer",
    "Dart Goblin",
)

# Альтернативные ответы на «мягкие» FB-цели (когда FB бережём на пак).
_ALT_ANSWERS: dict[str, tuple[str, ...]] = {
    "Witch": ("Valkyrie", "Knight", "Mini P.E.K.K.A", "Baby Dragon", "Poison", "Tornado"),
    "Wizard": ("Valkyrie", "Knight", "Mini P.E.K.K.A", "Goblin Gang", "Skeleton Army"),
    "Musketeer": ("Mini P.E.K.K.A", "Knight", "Goblin Gang", "Fireball"),
    "Magic Archer": ("The Log", "Arrows", "Fireball", "Valkyrie"),
    "Dart Goblin": ("The Log", "Arrows", "Barbarian Barrel", "Fireball"),
    "Mother Witch": ("Valkyrie", "Fireball", "Poison"),
    "Firecracker": ("The Log", "Arrows", "Zap", "Barbarian Barrel"),
}


def _ru(card: str) -> str:
    return card_name_ru(card) or card


def fireball_targets_in_deck(enemy: list[str]) -> list[str]:
    """Цели Fireball в колоде соперника, по убыванию приоритета."""
    present = set(enemy)
    return [t for t in FIREBALL_HOLD_PRIORITY if t in present]


def pick_fireball_hold(
    my_deck: list[str],
    enemy_deck: list[str],
) -> tuple[str | None, str]:
    """Главная цель для hold Fireball + текст причины.

    Если есть и пак (варвары/орда/кабаны/печь), и саппорт (ведьма) —
    бережём FB на пак; на ведьму предлагаем альтернативу из нашей колоды.
    """
    if "Fireball" not in my_deck:
        return None, ""

    targets = fireball_targets_in_deck(enemy_deck)
    if not targets:
        return None, ""

    primary = targets[0]
    soft = [t for t in targets[1:] if t in _ALT_ANSWERS]
    if soft:
        soft_card = soft[0]
        alt_candidates = _ALT_ANSWERS.get(soft_card, ())
        alt_in_deck = [c for c in alt_candidates if c in my_deck and c != "Fireball"]
        # Также любой сильный контр из counters_in_deck
        strong, partial = counters_in_deck(soft_card, my_deck)
        for c in strong + partial:
            if c != "Fireball" and c not in alt_in_deck:
                alt_in_deck.append(c)
        if alt_in_deck:
            alt = alt_in_deck[0]
            reason = (
                f"Береги на {_ru(primary)}; {_ru(soft_card)} закрывай {_ru(alt)}."
            )
            return primary, reason

    if len(targets) >= 2:
        others = ", ".join(_ru(t) for t in targets[1:3])
        reason = f"В первую очередь на {_ru(primary)} (также ценность vs {others})."
        return primary, reason

    return primary, f"Держи до появления {_ru(primary)}."


def spell_hold_targets(spell: str) -> tuple[str, ...]:
    """Приоритетный список целей для спелла (для tactical / match_plan)."""
    if spell == "Fireball":
        return FIREBALL_HOLD_PRIORITY
    return ()
