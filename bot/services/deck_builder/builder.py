"""Интеллектуальный генератор колод — 7 шагов."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from bot.services.card_data import WIN_CONDITIONS, card_has_role, get_card_elixir
from bot.services.card_matchups import calculate_deck_synergy, synergy_between
from bot.services.deck_builder.balance import (
    ScoreBreakdown,
    compute_score_breakdown,
    finalize_deck as balance_finalize_deck,
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

logger = logging.getLogger(__name__)

# Builder всегда сравнивает широкий набор вариантов до выбора победителя.
# Это не публичная настройка: количество можно наблюдать через DEBUG-лог.
_MIN_CANDIDATE_VARIANTS = 36
_MAX_TEMPLATE_CANDIDATES = 48

# Если в core несколько атакующих карт, это фиксированный приоритет именно
# для Builder. Он не меняет глобальный DeckIntent/Recommendation.
_PRIMARY_WIN_PRIORITY = (
    "Lava Hound",
    "Hog Rider",
    "Balloon",
    "Goblin Barrel",
    "Royal Giant",
    "Graveyard",
    "X-Bow",
    "Mortar",
    "Goblin Giant",
    "Ram Rider",
    "Battle Ram",
    "Wall Breakers",
    "Miner",
    "Mighty Miner",
)
_FAST_CYCLE_WINS = frozenset({
    "Hog Rider", "Goblin Barrel", "X-Bow", "Mortar", "Wall Breakers", "Miner",
})


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
    validation: object | None = None


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


def _core_primary_win(core: list[str]) -> str | None:
    """Выбранный пользователем win condition — якорь всей Builder-сборки."""
    core_set = set(core)
    for card in _PRIMARY_WIN_PRIORITY:
        if card in core_set:
            return card
    return next((card for card in core if card in WIN_CONDITIONS), None)


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
    from bot.services.deck_builder.win_plan_check import evaluate_win_plan

    if not evaluate_win_plan(deck, db, archetype).complete:
        return False
    breakdown = _build_score_breakdown(deck, core, db, archetype)
    core_avg = sum(
        _pair_synergy(db, c, d)
        for c in core
        for d in deck
        if c != d
    ) / max(len(core) * max(len(deck) - 1, 1), 1)
    return is_playable_balanced(breakdown, core_synergy_avg=core_avg)


def _validate_variant(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    decision,
    *,
    archetype: str | None = None,
    primary_anchor: str | None = None,
):
    """Единый gate: Builder возвращает только стабильные варианты."""
    from bot.services.deck_builder.validation import validate_builder_variant

    return validate_builder_variant(
        deck,
        core,
        db,
        # Гипотеза core не должна запретить более сильный вариант с другим
        # завершённым планом; итоговый архетип определяем после сборки.
        archetype=archetype or decision.archetype,
        intent=decision.intent,
        required_roles=decision.required_roles,
        mandatory_cards=decision.mandatory_cards,
        pair_synergy=lambda a, b: _pair_synergy(db, a, b),
        primary_anchor=primary_anchor,
    )


_REBUILD_ROLE_ORDER = (
    "big_spell",
    "small_spell",
    "air_defense",
    "anti_tank",
    "anti_swarm",
    "building",
    "cycle",
)


def _has_required_role(cards: list[str], role: str) -> bool:
    if role == "cycle":
        return any(card_has_role(card, role) or get_card_elixir(card) <= 2 for card in cards)
    return any(card_has_role(card, role) for card in cards)


def _required_role_seed(
    core: list[str],
    pool: set[str],
    db: DeckDatabase,
    decision,
) -> list[str]:
    """Детерминированная стартовая заготовка для пересборки без шаблона.

    Заполняет именно отсутствующие Required Roles, затем ``finalize_deck``
    выполняет обычную балансировку. Это не рекомендация Engine и не fallback
    случайной картой из set.
    """
    from bot.services.special_card_policy import SpecialCardPolicy

    seed = list(core)
    for role in _REBUILD_ROLE_ORDER:
        if len(seed) >= 8 or role not in decision.required_roles:
            continue
        if _has_required_role(seed, role):
            continue
        candidates = [
            card
            for card in sorted(pool)
            if card not in seed
            and card_has_role(card, role)
            and not SpecialCardPolicy.forbid_as_auto_pick(
                card,
                deck=seed,
                archetype=decision.archetype,
                intent=decision.intent,
                game_plan=decision.game_plan,
            )
        ]
        if not candidates:
            continue
        seed.append(max(
            candidates,
            key=lambda card: (
                sum(_pair_synergy(db, card, existing) for existing in seed),
                -get_card_elixir(card),
                card,
            ),
        ))
    # Добираем оставшиеся слоты недорогими не-spell картами. Это сохраняет
    # темп archetype и не даёт финальному добору зависеть от порядка set pool.
    while len(seed) < 8:
        candidates = [
            card
            for card in sorted(pool)
            if card not in seed
            and not is_spell(db, card)
            and get_card_elixir(card) <= 3
            and not SpecialCardPolicy.forbid_as_auto_pick(
                card,
                deck=seed,
                archetype=decision.archetype,
                intent=decision.intent,
                game_plan=decision.game_plan,
            )
        ]
        if not candidates:
            break
        seed.append(max(
            candidates,
            key=lambda card: (
                sum(_pair_synergy(db, card, existing) for existing in seed),
                -get_card_elixir(card),
                card,
            ),
        ))
    return seed


def _fillers_from_template(core: list[str], template: DeckRecord, db: DeckDatabase) -> list[str]:
    from bot.services.special_card_policy import SpecialCardPolicy

    core_set = set(core)
    arch = template.archetype
    core_has_win = any(c in WIN_CONDITIONS for c in core)

    def _ok(card: str) -> bool:
        # Mirror/Clone/… из похожей меты не тащим без явного контекста ядра/архетипа.
        return not SpecialCardPolicy.forbid_as_auto_pick(card, deck=core, archetype=arch)

    wins = [c for c in template.cards if c not in core_set and c in WIN_CONDITIONS and _ok(c)]
    troops = [
        c for c in template.cards
        if c not in core_set and c not in WIN_CONDITIONS and not is_spell(db, c)
        and c not in GENERIC_CARDS and _ok(c)
    ]
    spells = [
        c for c in template.cards
        if c not in core_set and is_spell(db, c) and c not in GENERIC_CARDS and _ok(c)
    ]
    generic = [
        c for c in template.cards
        if c not in core_set and c in GENERIC_CARDS and _ok(c)
    ]
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


def _candidate_archetype(deck: list[str], fallback: str) -> str:
    """Архетип готовой колоды — сигнал для оценки, не ограничение генерации."""
    detected = _detect_archetype(deck)
    return detected if detected != "Meta" else fallback


def _candidate_pool(
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    decision,
    primary_anchor: str | None,
) -> list[tuple[list[str], ScoredDeck | None, str]]:
    """Собрать минимум 30 различных сырых вариантов до валидации.

    Гипотеза архетипа лишь ранжирует шаблоны. Все шаблоны и контролируемые
    мутации non-core fillers остаются допустимыми кандидатами.
    """
    ranked = _rank_similar_decks(
        db,
        core,
        decision.archetype,
        limit=_MAX_TEMPLATE_CANDIDATES,
        decision=decision,
    )
    # Шаблон с пользовательским якорем предпочтительнее, но шаблоны другого
    # архетипа не запрещены: финальное решение остаётся за validation/score.
    if primary_anchor:
        ranked.sort(
            key=lambda source: (
                primary_anchor not in source.record.cards,
                -source.score,
                -source.confidence,
            ),
        )
    raw: list[tuple[list[str], ScoredDeck | None, str]] = []
    seen: set[str] = set()

    def add(deck: list[str], source: ScoredDeck | None, reason: str) -> None:
        key = _deck_key(deck)
        if len(deck) == 8 and key not in seen:
            seen.add(key)
            raw.append((deck, source, reason))

    # Каждому шаблону даём несколько разных стартовых fillers.
    for source in ranked:
        for filler_skip in range(4):
            add(
                _build_one_variant(
                    core,
                    db,
                    pool,
                    decision.archetype,
                    source.record,
                    filler_skip=filler_skip,
                ),
                source,
                f"template:{source.record.id}/skip:{filler_skip}",
            )

    # Если шаблонов недостаточно, строим альтернативы вокруг сильного seed,
    # меняя ровно один filler. Это именно генерация кандидатов, а не Improve.
    seed = _finalize_deck(
        _required_role_seed(core, pool, db, decision),
        core,
        db,
        pool,
        decision.archetype,
    )
    add(seed, None, "role-seed")
    core_set = set(core)
    replaceable = [card for card in seed if card not in core_set]
    from bot.services.special_card_policy import SpecialCardPolicy

    alternatives = [
        card
        for card in sorted(pool)
        if card not in seed
        and not SpecialCardPolicy.forbid_as_auto_pick(
            card,
            deck=seed,
            archetype=decision.archetype,
            intent=decision.intent,
            game_plan=decision.game_plan,
        )
    ]
    alternatives.sort(
        key=lambda card: (
            -sum(_pair_synergy(db, card, existing) for existing in core),
            get_card_elixir(card),
            card,
        ),
    )
    for drop in replaceable:
        for pick in alternatives:
            trial = list(seed)
            trial[trial.index(drop)] = pick
            add(
                _finalize_deck(trial, core, db, pool, decision.archetype),
                None,
                f"seed-mutation:{drop}->{pick}",
            )
            if len(raw) >= _MIN_CANDIDATE_VARIANTS:
                return raw

    return raw


def _result_rank(result: BuildResult, decision) -> float:
    """Одна формула выбора победителя после полной проверки кандидата."""
    from bot.services.deck_builder.constructor_decision import result_decision_bonus

    total = result.score_breakdown.total if result.score_breakdown else 0.0
    plan = result.validation.win_plan if result.validation else None
    plan_bonus = 12.0 if plan and plan.complete else 0.0
    pressure_bonus = 5.0 if plan and plan.constant_pressure and plan.counterattack else 0.0
    return (
        total * 0.45
        + result.synergy_score * 0.25
        + result.confidence * 0.15
        + result_decision_bonus(result.deck, decision) * 0.10
        + plan_bonus
        + pressure_bonus
    )


def _select_diverse_results(results: list[BuildResult], limit: int) -> list[BuildResult]:
    """Не возвращать ряд почти одинаковых списков карт, если есть альтернативы."""
    selected: list[BuildResult] = []
    for result in results:
        cards = set(result.deck)
        # Первые варианты могут быть близки, но после этого требуем хотя бы
        # две различающиеся карты относительно каждого выбранного.
        if len(selected) >= 2 and any(len(cards & set(item.deck)) >= 7 for item in selected):
            continue
        selected.append(result)
        if len(selected) >= limit:
            break
    # При бедном pool лучше вернуть валидную колоду, чем искусственно пустой UI.
    if not selected:
        return results[:limit]
    return selected


def _debug_builder(
    decision,
    primary_anchor: str | None,
    candidates: list[tuple[list[str], ScoredDeck | None, str]],
    rejected: list[tuple[str, list[str]]],
    accepted: list[BuildResult],
) -> None:
    """Диагностика без изменения API/UI, включается DECK_BUILDER_DEBUG=1."""
    if os.getenv("DECK_BUILDER_DEBUG", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    logger.info(
        "DeckBuilder: primary_anchor=%s archetype_hypothesis=%s game_plan=%s raw_candidates=%d accepted=%d rejected=%d",
        primary_anchor,
        decision.archetype,
        decision.game_plan.how_to_win,
        len(candidates),
        len(accepted),
        len(rejected),
    )
    for source, issues in rejected:
        logger.debug("DeckBuilder rejected candidate=%s issues=%s", source, ",".join(issues))
    for result in accepted:
        logger.debug(
            "DeckBuilder accepted deck=%s score=%.2f source=%s win_plan=%s",
            result.deck,
            _result_rank(result, decision),
            result.source_deck_id or "seed",
            result.validation.win_plan if result.validation else None,
        )


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
    from bot.services.deck_builder.constructor_decision import prepare_constructor_decision

    if len(core) not in (3, 4) or len(set(core)) != len(core):
        raise ValueError("Нужно 3 или 4 уникальные карты")

    db = db or get_database()
    if pool is None:
        pool = set(db.cards.keys())
    pool = set(pool) | set(core)

    # 1–2) Intent + GamePlan
    decision = prepare_constructor_decision(core, detect_archetype=_detect_archetype)
    archetype = decision.archetype
    primary_anchor = _core_primary_win(core)

    candidates = _candidate_pool(core, db, pool, decision, primary_anchor)
    accepted: list[BuildResult] = []
    rejected: list[tuple[str, list[str]]] = []
    for trial, source, reason in candidates:
        final_archetype = _candidate_archetype(trial, archetype)
        validation = _validate_variant(
            trial,
            core,
            db,
            decision,
            archetype=final_archetype,
            primary_anchor=primary_anchor,
        )
        if not validation.stable:
            rejected.append((reason, validation.issues))
            continue
        synergy_score, _ = calculate_deck_synergy(trial)
        confidence = source.confidence if source else 35.0
        accepted.append(BuildResult(
            deck=trial,
            archetype=final_archetype,
            average_elixir=_avg_elixir(trial, db),
            synergy_score=round(synergy_score, 1),
            confidence=round(confidence, 1),
            source_deck_id=source.record.id if source else None,
            balanced=True,
            score_breakdown=validation.score_breakdown,
            validation=validation,
        ))

    accepted.sort(key=lambda result: -_result_rank(result, decision))
    _debug_builder(decision, primary_anchor, candidates, rejected, accepted)
    if not accepted:
        raise ValueError(
            "Builder не смог построить стабильную колоду: "
            + ", ".join(rejected[-1][1] if rejected else ["no_candidates"]),
        )
    return accepted[0]


def build_multiple_decks(
    core: list[str],
    pool: set[str] | None = None,
    *,
    limit: int = 6,
) -> list[BuildResult]:
    """Несколько вариантов. Порядок: Intent → GamePlan → шаблоны → сборка.

    Публичный конструктор передаёт ровно 4 карты Core.
    Leave-one-out Core Conflict Analysis может собирать вокруг 3 карт.
    """
    from bot.services.deck_builder.constructor_decision import prepare_constructor_decision

    if len(core) not in (3, 4) or len(set(core)) != len(core):
        raise ValueError("Нужно 3 или 4 уникальные карты")

    db = get_database()
    if pool is None:
        pool = set(db.cards.keys())
    pool = set(pool) | set(core)

    decision = prepare_constructor_decision(core, detect_archetype=_detect_archetype)
    archetype = decision.archetype
    primary_anchor = _core_primary_win(core)
    candidates = _candidate_pool(core, db, pool, decision, primary_anchor)
    results: list[BuildResult] = []
    rejected: list[tuple[str, list[str]]] = []
    for deck, source, reason in candidates:
        final_archetype = _candidate_archetype(deck, archetype)
        validation = _validate_variant(
            deck,
            core,
            db,
            decision,
            archetype=final_archetype,
            primary_anchor=primary_anchor,
        )
        if not validation.stable:
            rejected.append((reason, validation.issues))
            continue
        synergy_score, _ = calculate_deck_synergy(deck)
        results.append(BuildResult(
            deck=deck,
            archetype=final_archetype,
            average_elixir=_avg_elixir(deck, db),
            synergy_score=round(synergy_score, 1),
            confidence=round(source.confidence if source else 35.0, 1),
            source_deck_id=source.record.id if source else None,
            balanced=True,
            score_breakdown=validation.score_breakdown,
            validation=validation,
        ))

    results = _dedupe_build_results(results)
    results.sort(key=lambda result: -_result_rank(result, decision))
    _debug_builder(decision, primary_anchor, candidates, rejected, results)
    return _select_diverse_results(results, limit)


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
