"""Контры и синергии карт.

Приоритет источников контров:
1. Ручные правила (MANUAL_COUNTERS, spells, offense WC)
2. DeckShop offline snapshot (если доступен)
3. Legacy COUNTERS из card_data
4. Роли карт (air_defense / anti_swarm / anti_tank)

Синергии: DeckShop → SYNERGIES из card_data.
Snapshot читается только с диска — без HTTP к DeckShop.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

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
    is_point_target_threat,
    is_pure_spell,
    is_spam_card,
    spell_counter_tier_vs_building,
)
from bot.services.card_names_ru import card_name_ru
from bot.services.deckshop_data import get_deckshop_status_summary, load_deckshop_snapshot


@dataclass(frozen=True)
class CardMatchups:
    name: str
    name_ru: str
    counters_strong: frozenset[str]
    counters_partial: frozenset[str]
    synergy_strong: frozenset[str]
    synergy_partial: frozenset[str]


# Воздушные угрозы для role-fallback (без импорта counter_engine).
_AIR_THREATS = frozenset({
    "Minions", "Minion Horde", "Baby Dragon", "Mega Minion", "Inferno Dragon",
    "Balloon", "Lava Hound", "Bats", "Skeleton Dragons", "Phoenix",
    "Flying Machine", "Electro Dragon",
})

_ROLE_AIR = "air_defense"
_ROLE_ANTI_SWARM = "anti_swarm"
_ROLE_ANTI_TANK = "anti_tank"
_ROLE_SPLASH = "splash"


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


@lru_cache(maxsize=1)
def _card_roles(name: str) -> frozenset[str]:
    try:
        from bot.services.deck_builder.loader import get_database

        rec = get_database().get_card(name)
        if rec:
            return rec.roles
    except Exception:
        pass
    return frozenset()


def _role_counter_tier(counter_card: str, target: str) -> str | None:
    """Базовый fallback по ролям — слабее DeckShop/manual."""
    roles = _card_roles(counter_card)
    if not roles:
        return None

    if target in _AIR_THREATS:
        if _ROLE_AIR in roles:
            return "partial"
        return None

    if is_spam_card(target):
        if _ROLE_ANTI_SWARM in roles or _ROLE_SPLASH in roles:
            return "partial"
        return None

    if is_point_target_threat(target) or target in {"Golem", "Giant", "Electro Giant", "P.E.K.K.A"}:
        if _ROLE_ANTI_TANK in roles:
            return "partial"
        return None

    if is_building(target):
        if _ROLE_SPLASH in roles:
            return "partial"

    return None


def _build_index(deckshop_counters: dict[str, dict]) -> dict[str, CardMatchups]:
    index: dict[str, CardMatchups] = {}
    for name, raw in deckshop_counters.items():
        if not isinstance(raw, dict):
            continue
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

    for name, partners in SYNERGIES.items():
        if name in index:
            existing = index[name]
            if existing.synergy_strong:
                continue
            index[name] = CardMatchups(
                name=existing.name,
                name_ru=existing.name_ru,
                counters_strong=existing.counters_strong,
                counters_partial=existing.counters_partial,
                synergy_strong=frozenset(_dedupe(partners)),
                synergy_partial=existing.synergy_partial,
            )
            continue
        index[name] = CardMatchups(
            name=name,
            name_ru=card_name_ru(name) or name,
            counters_strong=frozenset(),
            counters_partial=frozenset(),
            synergy_strong=frozenset(_dedupe(partners)),
            synergy_partial=frozenset(),
        )
    return index


_DECKSHOP_COUNTERS, _DECKSHOP_SOURCE, _DECKSHOP_STATUS = load_deckshop_snapshot()
_MATCHUPS: dict[str, CardMatchups] = _build_index(_DECKSHOP_COUNTERS)


def deckshop_matchup_status() -> dict:
    """Metadata snapshot для API/админки."""
    return get_deckshop_status_summary()


def deckshop_available() -> bool:
    return _DECKSHOP_STATUS.available


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
        tier = spell_counter_tier_vs_building(counter_card)
        if tier:
            return tier

    return _role_counter_tier(counter_card, target)


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
