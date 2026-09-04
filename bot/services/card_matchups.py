"""Контры и синергии карт.

Источник контров: DeckShop offline snapshot.

Правила Ghosteek поверх снимка: заклинание может контрить другую карту,
но само не имеет входящей карты-контры; основная атакующая карта не
выдаётся за защитную контру.

Синергии: DeckShop → SYNERGIES из card_data.
Snapshot читается только с диска — без HTTP к DeckShop.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.data.card_counter_policy import (
    COUNTER_SOURCES_EXCLUDED,
    COUNTER_TIER_OVERRIDES,
    MIRROR_ANSWER_TIERS,
)
from bot.services.card_data import (
    SYNERGIES,
    is_primary_win_condition,
    is_pure_spell,
)
from bot.services.card_names_ru import card_name_ru
from bot.services.deckshop_data import get_deckshop_status_summary, load_deckshop_snapshot

# TODO(card-profile): SYNERGIES remains legacy until its consumers migrate.


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


def _deckshop_counter_tier(counter_card: str, target: str) -> str | None:
    """DeckShop counters_vs_attack: counter_card бьёт target."""
    row = _matchups().get(counter_card)
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


def _build_index(deckshop_counters: dict[str, dict]) -> dict[str, CardMatchups]:
    index: dict[str, CardMatchups] = {}
    for name, raw in deckshop_counters.items():
        if not isinstance(raw, dict):
            continue
        attack_strong, attack_partial = _tier(raw.get("counters_vs_attack"))
        defense_strong, defense_partial = _tier(raw.get("counters_vs_defense"))
        strong = _dedupe(attack_strong + defense_strong)
        partial = [target for target in _dedupe(attack_partial + defense_partial) if target not in strong]
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
# Ленивая индексация: _build_index вызывает is_pure_spell → get_card_profile.
# Eager init на import ломал роли через цикл deck_builder package.
_MATCHUPS: dict[str, CardMatchups] | None = None


def _matchups() -> dict[str, CardMatchups]:
    global _MATCHUPS
    if _MATCHUPS is None:
        _MATCHUPS = _build_index(_DECKSHOP_COUNTERS)
    return _MATCHUPS


def deckshop_matchup_status() -> dict:
    """Metadata snapshot для API/админки."""
    return get_deckshop_status_summary()


def deckshop_available() -> bool:
    return _DECKSHOP_STATUS.available


def get_matchups(card: str) -> CardMatchups | None:
    return _matchups().get(card)


def ru(card: str, *, short: bool = True) -> str:
    row = _matchups().get(card)
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
        # Саму карту не записываем в граф контр, но в колоде она может быть
        # зеркальным защитным ответом (например, Валькирия на Валькирию).
        tier = (
            MIRROR_ANSWER_TIERS.get(card)
            if card == threat
            else card_counters_target(card, threat)
        )
        if tier == "strong":
            strong.append(card)
        elif tier == "partial":
            partial.append(card)
    return _dedupe(strong), _dedupe(partial)


def card_counters_target(counter_card: str, target: str) -> str | None:
    """'strong' | 'partial' | None — контрит ли counter_card карту target."""
    if counter_card == target:
        return None

    if counter_card in COUNTER_SOURCES_EXCLUDED:
        return None

    # Win condition — план атаки на башню, не универсальный защитный ответ.
    # Вторичное давление (например, Mighty Miner) не исключаем: такие карты
    # могут быть подтверждённой контрой в обороне.
    if is_primary_win_condition(counter_card):
        return None

    # Заклинание может контрить карту, но само не имеет входящей контры.
    if is_pure_spell(target):
        return None
    override = COUNTER_TIER_OVERRIDES.get(counter_card, {}).get(target)
    if override:
        return override
    return _deckshop_counter_tier(counter_card, target)


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
    row = _matchups().get(a)
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
    row = _matchups().get(card)
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
    """Совместимый адаптер к единому MatchupEvaluation.

    Исторически функция считала покрытие контрами отдельно и использовала
    обратную семантику. Теперь число означает сложность для defender_deck.
    """
    from bot.services.matchup_evaluation import evaluate_matchup

    return float(evaluate_matchup(defender_deck, attacker_deck).score)


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
    """Оценка внутренней синергии колоды 0–100 и короткие строки на русском.

    Адаптер к DeckSynergyEvaluation: core + roles + gameplan − conflicts.

    .. deprecated::
        Для полной оценки колоды используйте
        ``DeckEvaluator.evaluate(...).synergy`` / ``EvaluationReport``.
        Функция сохранена для совместимости и внутренних осей.
    """
    from bot.services.deck_synergy import evaluate_deck_synergy

    evaluation = evaluate_deck_synergy(cards)
    return evaluation.score, evaluation.notes
