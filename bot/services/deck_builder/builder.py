"""Интеллектуальный генератор колод — 7 шагов."""

from __future__ import annotations

from dataclasses import dataclass

from bot.services.card_data import WIN_CONDITIONS, get_card_elixir
from bot.services.card_matchups import calculate_deck_synergy, synergy_between
from bot.services.deck_builder.balance import (
    ScoreBreakdown,
    compute_score_breakdown,
    finalize_deck as balance_finalize_deck,
    hard_constraint_issues,
    is_attack_win,
    is_playable_balanced,
    is_spell,
)
from bot.services.deck_builder.constants import (
    ARCHETYPE_ELIXIR,
    ARCHETYPE_PRIMARY_WIN,
    DEFAULT_ELIXIR_MAX,
    DEFAULT_ELIXIR_MIN,
    GENERIC_CARDS,
    KNOWN_SYNERGY_PAIRS,
    SYNERGY_PARTIAL,
    SYNERGY_STRONG,
    SYNERGY_WEAK,
    WEIGHT_ARCHETYPE,
    WEIGHT_CARD_MATCH,
    WEIGHT_ELIXIR,
    WEIGHT_POPULARITY,
    WEIGHT_SYNERGY,
)
from bot.services.deck_builder.loader import DeckDatabase, DeckRecord, get_database


@dataclass
class BuildResult:
    deck: list[str]
    archetype: str
    average_elixir: float
    synergy_score: float
    confidence: float
    source_deck_id: str | None = None
    balanced: bool = True
    score_breakdown: ScoreBreakdown | None = None


@dataclass
class ScoredDeck:
    record: DeckRecord
    score: float
    confidence: float
    overlap: int


def _avg_elixir(cards: list[str], db: DeckDatabase) -> float:
    if not cards:
        return 0.0
    total = sum(db.get_card(c).elixir if db.get_card(c) else get_card_elixir(c) for c in cards)
    return round(total / len(cards), 2)


def _detect_archetype(core: list[str]) -> str:
    """Публичная точка для builder/improver — мультифакторный скоринг."""
    from bot.services.deck_builder.archetype_detect import detect_archetype_from_cards

    return detect_archetype_from_cards(core)


def _pair_synergy(db: DeckDatabase, a: str, b: str) -> int:
    key = frozenset({a, b})
    if key in KNOWN_SYNERGY_PAIRS:
        return KNOWN_SYNERGY_PAIRS[key]
    if key in db.synergy_pairs:
        return db.synergy_pairs[key]
    tier = synergy_between(a, b)
    if tier == "strong":
        return SYNERGY_STRONG
    if tier == "partial":
        return SYNERGY_PARTIAL
    return SYNERGY_WEAK


def _meaningful_overlap(core: list[str], template_cards: list[str]) -> list[str]:
    core_set = set(core)
    return [c for c in template_cards if c in core_set and c not in GENERIC_CARDS]


def _template_is_usable(core: list[str], template: DeckRecord) -> bool:
    core_set = set(core)
    meaningful = _meaningful_overlap(core, list(template.cards))
    if len(meaningful) >= 2:
        return True

    primary = ARCHETYPE_PRIMARY_WIN.get(template.archetype, [])
    if any(w in core_set for w in primary) and len(meaningful) >= 1:
        return True

    if any(c in WIN_CONDITIONS for c in core) and len(meaningful) >= 1:
        return True

    template_wins = [c for c in template.cards if c in WIN_CONDITIONS]
    if template_wins and not any(w in core_set for w in template_wins):
        return False

    return len(meaningful) >= 1


def _overlap_score(core: list[str], template_cards: list[str]) -> float:
    core_set = set(core)
    score = 0.0
    for card in template_cards:
        if card not in core_set:
            continue
        score += 0.5 if card in GENERIC_CARDS else 4.0
        if card in WIN_CONDITIONS:
            score += 6.0
    return score


def _core_synergy_with_deck(db: DeckDatabase, core: list[str], deck_cards: list[str]) -> float:
    total, n = 0.0, 0
    for c in core:
        for d in deck_cards:
            if c != d:
                total += _pair_synergy(db, c, d)
                n += 1
    return total / n if n else 0.0


def _score_deck_match(
    db: DeckDatabase,
    core: list[str],
    archetype: str,
    record: DeckRecord,
) -> ScoredDeck | None:
    if not _template_is_usable(core, record):
        return None

    weighted = _overlap_score(core, list(record.cards))
    card_score = weighted * (WEIGHT_CARD_MATCH / 4)
    arch_score = WEIGHT_ARCHETYPE if record.archetype == archetype else 0.0
    elixir_diff = abs(record.avg_elixir - _avg_elixir(core, db))
    elixir_score = max(0.0, WEIGHT_ELIXIR - elixir_diff * 5.0)
    syn_score = (_core_synergy_with_deck(db, core, list(record.cards)) / 100.0) * WEIGHT_SYNERGY
    pop_score = (record.popularity / 100.0) * WEIGHT_POPULARITY

    raw = card_score + arch_score + elixir_score + syn_score + pop_score
    max_possible = 4 * WEIGHT_CARD_MATCH + WEIGHT_ARCHETYPE + WEIGHT_ELIXIR + WEIGHT_SYNERGY + WEIGHT_POPULARITY
    confidence = min(100.0, (raw / max_possible) * 100.0)
    overlap = len(_meaningful_overlap(core, list(record.cards)))
    return ScoredDeck(record=record, score=raw, confidence=confidence, overlap=overlap)


def _rank_similar_decks(
    db: DeckDatabase,
    core: list[str],
    archetype: str,
    *,
    limit: int = 12,
    decision=None,
) -> list[ScoredDeck]:
    from bot.services.deck_builder.constructor_decision import template_decision_bonus

    indices = db.candidate_indices(core)
    scored: list[ScoredDeck] = []
    for idx in indices:
        sd = _score_deck_match(db, core, archetype, db.decks[idx])
        if sd:
            if decision is not None:
                extra = template_decision_bonus(sd.record, decision)
                sd = ScoredDeck(
                    record=sd.record,
                    score=sd.score + extra,
                    confidence=min(100.0, sd.confidence + extra * 0.35),
                    overlap=sd.overlap,
                )
            scored.append(sd)
    if not scored:
        for record in db.decks:
            sd = _score_deck_match(db, core, archetype, record)
            if sd:
                if decision is not None:
                    extra = template_decision_bonus(sd.record, decision)
                    sd = ScoredDeck(
                        record=sd.record,
                        score=sd.score + extra,
                        confidence=min(100.0, sd.confidence + extra * 0.35),
                        overlap=sd.overlap,
                    )
                scored.append(sd)
    scored.sort(key=lambda x: (-x.score, -x.confidence, -x.overlap))
    return scored[:limit]


def _build_score_breakdown(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    archetype: str,
) -> ScoreBreakdown:
    return compute_score_breakdown(deck, db, core, archetype, pair_synergy=lambda a, b: _pair_synergy(db, a, b))


def _result_balanced(deck: list[str], core: list[str], db: DeckDatabase, archetype: str) -> bool:
    breakdown = _build_score_breakdown(deck, core, db, archetype)
    core_avg = sum(
        _pair_synergy(db, c, d)
        for c in core
        for d in deck
        if c != d
    ) / max(len(core) * max(len(deck) - 1, 1), 1)
    return is_playable_balanced(breakdown, core_synergy_avg=core_avg)


def _fillers_from_template(core: list[str], template: DeckRecord, db: DeckDatabase) -> list[str]:
    core_set = set(core)
    core_has_win = any(c in WIN_CONDITIONS for c in core)
    wins = [c for c in template.cards if c not in core_set and c in WIN_CONDITIONS]
    troops = [
        c for c in template.cards
        if c not in core_set and c not in WIN_CONDITIONS and not is_spell(db, c) and c not in GENERIC_CARDS
    ]
    spells = [
        c for c in template.cards
        if c not in core_set and is_spell(db, c) and c not in GENERIC_CARDS
    ]
    generic = [c for c in template.cards if c not in core_set and c in GENERIC_CARDS]
    ordered = ([] if core_has_win else wins[:1]) + troops + spells + generic
    return ordered[:4]


def _finalize_deck(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
) -> list[str]:
    return balance_finalize_deck(
        deck,
        core,
        db,
        pool,
        archetype,
        lambda a, b: _pair_synergy(db, a, b),
    )


def _build_one_variant(
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
    template: DeckRecord | None = None,
    *,
    filler_skip: int = 0,
) -> list[str]:
    fillers = _fillers_from_template(core, template, db) if template else []
    if filler_skip:
        fillers = fillers[filler_skip:]
    deck = list(core)
    for card in fillers:
        if len(deck) >= 8:
            break
        if card not in deck:
            deck.append(card)
    arch = template.archetype if template else archetype
    return _finalize_deck(deck, core, db, pool, arch)


def build_deck_from_core(
    core: list[str],
    pool: set[str] | None = None,
    *,
    db: DeckDatabase | None = None,
) -> BuildResult:
    """Сборка колоды.

    Порядок решений:
      1) DeckIntent → 2) GamePlan → 3) шаблон → 4–6) кандидаты / оценка / finalize
    (существующий finalize сохранён).
    """
    from bot.services.deck_builder.constructor_decision import (
        prepare_constructor_decision,
        result_decision_bonus,
    )

    if len(core) != 4 or len(set(core)) != 4:
        raise ValueError("Нужно ровно 4 уникальные карты")

    db = db or get_database()
    if pool is None:
        pool = set(db.cards.keys())
    pool = set(pool) | set(core)

    # 1–2) Intent + GamePlan
    decision = prepare_constructor_decision(core, detect_archetype=_detect_archetype)
    archetype = decision.archetype

    # 3) Выбор шаблона (с bias Intent/GamePlan)
    ranked = _rank_similar_decks(db, core, archetype, limit=6, decision=decision)
    best = ranked[0] if ranked else None

    # 4–6) Кандидаты из шаблона → оценка finalize → итоговая колода
    deck = _build_one_variant(core, db, pool, archetype, best.record if best else None)
    synergy_score, _ = calculate_deck_synergy(deck)
    breakdown = _build_score_breakdown(deck, core, db, archetype)
    # лёгкая подстройка confidence под decision-fit (API BuildResult без новых полей)
    conf = round(best.confidence if best else 35.0, 1)
    conf = min(100.0, conf + result_decision_bonus(deck, decision) * 0.4)

    return BuildResult(
        deck=deck,
        archetype=archetype,
        average_elixir=_avg_elixir(deck, db),
        synergy_score=round(synergy_score, 1),
        confidence=round(conf, 1),
        source_deck_id=best.record.id if best else None,
        balanced=_result_balanced(deck, core, db, archetype),
        score_breakdown=breakdown,
    )


def build_multiple_decks(
    core: list[str],
    pool: set[str] | None = None,
    *,
    limit: int = 6,
) -> list[BuildResult]:
    """Несколько вариантов. Порядок: Intent → GamePlan → шаблоны → сборка."""
    from bot.services.deck_builder.constructor_decision import (
        prepare_constructor_decision,
        result_decision_bonus,
    )

    db = get_database()
    if pool is None:
        pool = set(db.cards.keys())
    pool = set(pool) | set(core)

    decision = prepare_constructor_decision(core, detect_archetype=_detect_archetype)
    archetype = decision.archetype
    ranked = _rank_similar_decks(db, core, archetype, limit=limit * 5, decision=decision)

    results: list[BuildResult] = []
    seen: set[str] = set()

    for sd in ranked:
        if len(results) >= limit:
            break
        for filler_skip in (0, 1, 2):
            deck = _build_one_variant(core, db, pool, archetype, sd.record, filler_skip=filler_skip)
            arch = sd.record.archetype or archetype
            if len(deck) != 8 or hard_constraint_issues(deck, db, core):
                continue
            key = _deck_key(deck)
            if key in seen:
                continue
            seen.add(key)
            synergy_score, _ = calculate_deck_synergy(deck)
            breakdown = _build_score_breakdown(deck, core, db, arch)
            conf = min(100.0, sd.confidence + result_decision_bonus(deck, decision) * 0.4)
            results.append(BuildResult(
                deck=deck,
                archetype=arch,
                average_elixir=_avg_elixir(deck, db),
                synergy_score=round(synergy_score, 1),
                confidence=round(conf, 1),
                source_deck_id=sd.record.id,
                balanced=_result_balanced(deck, core, db, arch),
                score_breakdown=breakdown,
            ))
            break

    if not results:
        deck = _build_one_variant(core, db, pool, archetype)
        key = _deck_key(deck)
        seen.add(key)
        synergy_score, _ = calculate_deck_synergy(deck)
        breakdown = _build_score_breakdown(deck, core, db, archetype)
        conf = 35.0 + result_decision_bonus(deck, decision) * 0.4
        results.append(BuildResult(
            deck=deck,
            archetype=archetype,
            average_elixir=_avg_elixir(deck, db),
            synergy_score=round(synergy_score, 1),
            confidence=round(min(100.0, conf), 1),
            balanced=_result_balanced(deck, core, db, archetype),
            score_breakdown=breakdown,
        ))

    fallback = _finalize_deck(core, core, db, pool, archetype)
    fkey = _deck_key(fallback)
    if fkey not in seen and len(results) < limit:
        synergy_score, _ = calculate_deck_synergy(fallback)
        breakdown = _build_score_breakdown(fallback, core, db, archetype)
        conf = 30.0 + result_decision_bonus(fallback, decision) * 0.4
        results.append(BuildResult(
            deck=fallback,
            archetype=archetype,
            average_elixir=_avg_elixir(fallback, db),
            synergy_score=round(synergy_score, 1),
            confidence=round(min(100.0, conf), 1),
            balanced=_result_balanced(fallback, core, db, archetype),
            score_breakdown=breakdown,
        ))

    def _rank_key(r: BuildResult) -> float:
        total = r.score_breakdown.total if r.score_breakdown else 0.0
        fit = result_decision_bonus(r.deck, decision)
        return total * 0.45 + r.synergy_score * 0.25 + r.confidence * 0.15 + fit * 0.15

    results.sort(key=lambda r: -_rank_key(r))
    return _dedupe_build_results(results)[:limit]


def _deck_key(deck: list[str]) -> str:
    return "|".join(sorted(deck))


def _dedupe_build_results(results: list[BuildResult]) -> list[BuildResult]:
    out: list[BuildResult] = []
    seen: set[str] = set()
    for item in results:
        key = _deck_key(item.deck)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


# Совместимость для deck_improver / deck_detail (не используются в finalize).
def _card_roles(db: DeckDatabase, name: str) -> frozenset[str]:
    from bot.services.deck_builder.balance import _card_roles as _roles

    return _roles(db, name)


def _card_has_role(db: DeckDatabase, name: str, role: str) -> bool:
    from bot.services.deck_builder.balance import _card_has_role as _has

    return _has(db, name, role)


def _count_spells(deck: list[str], db: DeckDatabase) -> int:
    return sum(1 for c in deck if is_spell(db, c))


def _count_wins(deck: list[str], db: DeckDatabase) -> int:
    # Совпадает с finalize / hard MAX_WINS (только attack-wins).
    return sum(1 for c in deck if is_attack_win(c))


def _is_spell(db: DeckDatabase, name: str) -> bool:
    return is_spell(db, name)


def _is_win(db: DeckDatabase, name: str) -> bool:
    return is_attack_win(name)


def _elixir_bounds(archetype: str) -> tuple[float, float]:
    return ARCHETYPE_ELIXIR.get(archetype, (DEFAULT_ELIXIR_MIN, DEFAULT_ELIXIR_MAX))
