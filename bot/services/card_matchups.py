"""Контры и синергии карт (данные DeckShop, локализация под бота).

Источник: bot/data/deckshop_counters.py — локальный снимок, без запросов к сайту.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.data.deckshop_counters import DECKSHOP_COUNTERS
from bot.services.card_data import (
    COUNTERS,
    MANUAL_COUNTERS_PARTIAL,
    MANUAL_COUNTERS_STRONG,
    OFFENSE_COUNTER_ALLOWED,
    SYNERGIES,
    card_counters_for_spell,
    get_card_elixir,
    is_building,
    is_offense_win_condition,
    is_pure_spell,
    spell_counter_tier_vs_building,
)
from bot.services.card_names_ru import card_name_ru


@dataclass(frozen=True)
class CardMatchups:
    name: str
    name_ru: str
    counters_strong: frozenset[str]
    counters_partial: frozenset[str]
    synergy_strong: frozenset[str]
    synergy_partial: frozenset[str]


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _apply_spell_counter_rules(name: str, strong: list[str], partial: list[str]) -> tuple[list[str], list[str]]:
    """На заклинания нет карты-контры, кроме Монаха на Фаербол/Ракету."""
    if is_pure_spell(name):
        return _dedupe(card_counters_for_spell(name)), []
    return strong, partial


def _deckshop_counter_tier(counter_card: str, target: str) -> str | None:
    """DeckShop counters_vs_attack: counter_card бьёт target."""
    row = _MATCHUPS.get(counter_card)
    if not row:
        return None
    if target in row.counters_strong:
        return "strong"
    if target in row.counters_partial:
        return "partial"
    return None


def _tier(raw: dict | None) -> tuple[list[str], list[str]]:
    if not raw:
        return [], []
    return _dedupe(raw.get("strong") or []), _dedupe(raw.get("partial") or [])


def _build_index() -> dict[str, CardMatchups]:
    index: dict[str, CardMatchups] = {}
    for name, raw in DECKSHOP_COUNTERS.items():
        strong, partial = _tier(raw.get("counters_vs_attack"))
        strong, partial = _apply_spell_counter_rules(name, strong, partial)
        syn_strong, syn_partial = _tier(raw.get("synergy_offense"))
        if not syn_strong and not syn_partial and name in SYNERGIES:
            syn_strong = _dedupe(SYNERGIES[name])
        index[name] = CardMatchups(
            name=name,
            name_ru=(raw.get("name_ru") or card_name_ru(name) or name).strip(),
            counters_strong=frozenset(strong),
            counters_partial=frozenset(partial),
            synergy_strong=frozenset(syn_strong),
            synergy_partial=frozenset(syn_partial),
        )
    return index


_MATCHUPS: dict[str, CardMatchups] = _build_index()


def get_matchups(card: str) -> CardMatchups | None:
    return _MATCHUPS.get(card)


def ru(card: str, *, short: bool = True) -> str:
    row = _MATCHUPS.get(card)
    if row and row.name_ru:
        return row.name_ru if not short else card_name_ru(card, short=True) or row.name_ru
    return card_name_ru(card, short=short) or card


def ru_list(cards: list[str], *, limit: int = 4) -> str:
    return ", ".join(ru(c) for c in cards[:limit])


def counters_in_deck(threat: str, deck: list[str]) -> tuple[list[str], list[str]]:
    """Какие карты из колоды контрят угрозу (сильно / частично)."""
    strong: list[str] = []
    partial: list[str] = []
    for card in deck:
        if card == threat:
            continue
        tier = card_counters_target(card, threat)
        if tier == "strong":
            strong.append(card)
        elif tier == "partial":
            partial.append(card)
    return _dedupe(strong), _dedupe(partial)


def card_counters_target(counter_card: str, target: str) -> str | None:
    """'strong' | 'partial' | None — контрит ли counter_card карту target."""
    if counter_card == target:
        return None

    if is_pure_spell(target):
        if counter_card in card_counters_for_spell(target):
            return "strong"
        return None

    if target in MANUAL_COUNTERS_STRONG.get(counter_card, ()):
        return "strong"
    if target in MANUAL_COUNTERS_PARTIAL.get(counter_card, ()):
        return "partial"

    allowed_offense = OFFENSE_COUNTER_ALLOWED.get(counter_card)
    if allowed_offense is not None:
        return "strong" if target in allowed_offense else None

    if is_offense_win_condition(counter_card):
        return None

    tier = _deckshop_counter_tier(counter_card, target)
    if tier:
        return tier

    if counter_card in COUNTERS.get(target, []):
        return "strong"

    if is_building(target):
        return spell_counter_tier_vs_building(counter_card)

    return None


def targets_countered_by(card: str, opponent_deck: list[str]) -> tuple[list[str], list[str]]:
    """Какие карты соперника наша карта контрит."""
    strong: list[str] = []
    partial: list[str] = []
    for target in opponent_deck:
        if target == card:
            continue
        tier = card_counters_target(card, target)
        if tier == "strong":
            strong.append(target)
        elif tier == "partial":
            partial.append(target)
    return strong, partial


def synergy_between(a: str, b: str) -> str | None:
    """Есть ли синергия a→b: strong / partial / None."""
    if a == b:
        return None
    row = _MATCHUPS.get(a)
    if not row:
        if b in SYNERGIES.get(a, []):
            return "strong"
        return None
    if b in row.synergy_strong:
        return "strong"
    if b in row.synergy_partial:
        return "partial"
    return None


_SPIRIT_CARDS = frozenset({"Ice Spirit", "Fire Spirit", "Electro Spirit", "Heal Spirit"})


def _is_spirit_card(name: str) -> bool:
    return name in _SPIRIT_CARDS


def _is_attacking_card(name: str) -> bool:
    return is_offense_win_condition(name)


def is_valid_synergy_pair(a: str, b: str) -> bool:
    """Синергия только с участием атакующей карты; духи/здания/заклинания — не между собой."""
    if a == b:
        return False
    if _is_spirit_card(a) and (is_pure_spell(b) or is_building(b)):
        return False
    if _is_spirit_card(b) and (is_pure_spell(a) or is_building(a)):
        return False
    if is_pure_spell(a) and is_building(b):
        return False
    if is_pure_spell(b) and is_building(a):
        return False
    if is_pure_spell(a) and is_pure_spell(b):
        return False
    return _is_attacking_card(a) or _is_attacking_card(b)


def synergy_partners(
    card: str,
    pool: list[str] | None = None,
    *,
    limit: int = 6,
) -> tuple[list[str], list[str]]:
    """Сильные и слабые синергичные карты (из pool или все известные)."""
    row = _MATCHUPS.get(card)
    if not row:
        legacy = SYNERGIES.get(card, [])
        if pool is not None:
            legacy = [c for c in legacy if c in pool]
        return _dedupe(legacy)[:limit], []

    allowed = set(pool) if pool is not None else None
    strong = [c for c in row.synergy_strong if c != card and (allowed is None or c in allowed)]
    partial = [
        c for c in row.synergy_partial
        if c != card and c not in strong and (allowed is None or c in allowed)
    ]
    return _dedupe(strong)[:limit], _dedupe(partial)[:limit]


def calculate_matchup_score(defender_deck: list[str], attacker_deck: list[str]) -> float:
    """0–100: насколько defender_deck отвечает на карты attacker_deck."""
    if not attacker_deck:
        return 50.0

    points = 0.0
    for threat in attacker_deck:
        strong, partial = counters_in_deck(threat, defender_deck)
        if strong:
            points += 1.0
        elif partial:
            points += 0.45
        else:
            points += 0.0

    base = (points / len(attacker_deck)) * 100.0

    def _avg(cards: list[str]) -> float:
        xs = [get_card_elixir(c) for c in cards]
        return sum(xs) / len(xs) if xs else 0.0

    def_avg = _avg(defender_deck)
    att_avg = _avg(attacker_deck)
    if def_avg > att_avg + 1.0:
        base -= 8
    elif def_avg < att_avg - 0.5:
        base += 4

    return round(max(0.0, min(100.0, base)), 1)


def _synergy_tier_pair(a: str, b: str) -> str | None:
    """Сильнейший уровень синергии для неупорядоченной пары."""
    tier_a = synergy_between(a, b)
    tier_b = synergy_between(b, a)
    if tier_a == "strong" or tier_b == "strong":
        return "strong"
    if tier_a == "partial" or tier_b == "partial":
        return "partial"
    return None


def calculate_deck_synergy(cards: list[str]) -> tuple[float, list[str]]:
    """Оценка внутренней синергии колоды 0–100 и короткие строки на русском."""
    if len(cards) < 2:
        return 50.0, []

    total = 0.0
    pairs = 0
    highlights: list[str] = []
    seen_highlight_keys: set[tuple[str, str]] = set()

    for i, a in enumerate(cards):
        for b in cards[i + 1 :]:
            if not is_valid_synergy_pair(a, b):
                continue
            tier = _synergy_tier_pair(a, b)
            pairs += 1
            if tier == "strong":
                total += 1.0
                key = tuple(sorted((a, b)))
                if key not in seen_highlight_keys and len(highlights) < 6:
                    seen_highlight_keys.add(key)
                    left, right = sorted((a, b))
                    highlights.append(f"{ru(left)} + {ru(right)}")
            elif tier == "partial":
                total += 0.35

    score = (total / pairs) * 100.0 if pairs else 50.0
    return round(score, 1), highlights
