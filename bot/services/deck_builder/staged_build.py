"""Многостадийная сборка колоды: шаблоны → freeform → архетип.

Пользователь никогда не должен видеть внутренние отказы конструктора.
Если карта существует — обязан вернуться готовый вариант из 8 карт.
"""

from __future__ import annotations

import logging
from typing import Any

from bot.services.card_data import WIN_CONDITIONS, get_card_elixir
from bot.services.card_matchups import synergy_between
from bot.services.card_names_ru import card_name_ru
from bot.services.counter_engine import _get_arena_pool
from bot.services.deck_builder.balance import is_attack_win
from bot.services.deck_builder.builder import (
    BuildResult,
    _avg_elixir,
    _candidate_archetype,
    _candidate_pool,
    _core_primary_win,
    _detect_archetype,
    _pair_synergy,
    _result_rank,
    _validate_variant,
    build_multiple_decks,
)
from bot.services.deck_builder.constructor_decision import prepare_constructor_decision
from bot.services.deck_builder.constants import (
    ARCHETYPE_ANCHORS,
    SYNERGY_PARTIAL,
    SYNERGY_STRONG,
)
from bot.services.deck_builder.loader import get_database
from bot.services.deck_evaluator.evaluator import DeckEvaluator
from bot.services.meta_decks import META_DECKS

logger = logging.getLogger(__name__)

STAGE_META = "meta_templates"
STAGE_FREEFORM = "freeform_anchor"
STAGE_ARCHETYPE = "archetype_fallback"

# Ближайшие рабочие архетипы, если карта не в curated meta.
_CARD_ARCHETYPE_HINTS: dict[str, tuple[str, ...]] = {
    "Giant Skeleton": ("Bridge Spam", "Control", "Beatdown"),
    "Sparky": ("Bridge Spam", "Control", "Beatdown"),
    "Electro Giant": ("Beatdown", "Control"),
    "Elixir Golem": ("Beatdown", "Bridge Spam"),
    "Goblin Giant": ("Beatdown", "Bridge Spam"),
    "Battle Healer": ("Bridge Spam", "Beatdown"),
    "Three Musketeers": ("Beatdown", "Control"),
}


def _card_known(name: str) -> bool:
    if not name:
        return False
    db = get_database()
    if name in db.cards:
        return True
    from bot.services.card_data import CARD_META

    return name in CARD_META


def _synergy_score(db, a: str, b: str) -> int:
    key = frozenset({a, b})
    from bot.services.deck_builder.constants import KNOWN_SYNERGY_PAIRS

    if key in KNOWN_SYNERGY_PAIRS:
        return int(KNOWN_SYNERGY_PAIRS[key])
    if key in db.synergy_pairs:
        return int(db.synergy_pairs[key])
    tier = synergy_between(a, b)
    if tier == "strong":
        return SYNERGY_STRONG
    if tier == "partial":
        return SYNERGY_PARTIAL
    return 40


def _expand_seed_core(seed: list[str], pool: set[str], db) -> list[str]:
    """Вырастить 1–2 карты до ядра 3–4 для существующего builder API."""
    core = list(dict.fromkeys(seed))  # unique, keep order
    if not any(is_attack_win(c) or c in WIN_CONDITIONS for c in core):
        wins = [
            c for c in pool
            if c not in core and (is_attack_win(c) or c in WIN_CONDITIONS)
        ]
        wins.sort(
            key=lambda c: (
                -sum(_synergy_score(db, c, s) for s in core),
                get_card_elixir(c),
                c,
            ),
        )
        if wins:
            core.append(wins[0])

    # Добавим дешёвую поддержку / cycle, чтобы Intent увереннее угадал стиль.
    while len(core) < 3:
        candidates = [
            c for c in pool
            if c not in core and get_card_elixir(c) <= 3 and not is_attack_win(c)
        ]
        if not candidates:
            break
        candidates.sort(
            key=lambda c: (
                -sum(_synergy_score(db, c, s) for s in core),
                get_card_elixir(c),
                c,
            ),
        )
        core.append(candidates[0])

    return core[:4]


def _best_effort_from_core(
    core: list[str],
    pool: set[str],
    *,
    limit: int = 3,
) -> list[BuildResult]:
    """Собрать варианты; если stable нет — взять лучшие по evaluation."""
    if len(core) in (3, 4):
        try:
            stable = build_multiple_decks(core, pool, limit=limit)
            if stable:
                return stable
        except ValueError:
            pass

    db = get_database()
    pool = set(pool) | set(core)
    decision = prepare_constructor_decision(core, detect_archetype=_detect_archetype)
    primary_anchor = _core_primary_win(core) or core[0]
    # Для якоря вне WIN_CONDITIONS всё равно держим его как primary.
    if primary_anchor not in core:
        primary_anchor = core[0]

    candidates = _candidate_pool(core, db, pool, decision, primary_anchor)
    scored: list[BuildResult] = []
    for trial, source, _reason in candidates:
        if len(trial) != 8:
            continue
        final_archetype = _candidate_archetype(trial, decision.archetype)
        validation = _validate_variant(
            trial,
            core,
            db,
            decision,
            archetype=final_archetype,
            primary_anchor=primary_anchor,
        )
        evaluation = validation.evaluation
        if evaluation is None:
            evaluation = DeckEvaluator.evaluate(
                trial, core=core, archetype=final_archetype, db=db,
            )
        scored.append(BuildResult(
            deck=trial,
            archetype=final_archetype,
            average_elixir=_avg_elixir(trial, db),
            confidence=round(source.confidence if source else 28.0, 1),
            source_deck_id=source.record.id if source else None,
            balanced=validation.stable,
            validation=validation,
            evaluation=evaluation,
        ))

    if not scored:
        return []

    scored.sort(
        key=lambda r: (
            0 if r.balanced else 1,
            -_result_rank(r, decision) if r.validation else -(r.evaluation.total_score if r.evaluation else 0),
        ),
    )
    # Diversify lightly
    out: list[BuildResult] = []
    seen: set[str] = set()
    for item in scored:
        key = "|".join(sorted(item.deck))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _archetype_candidates_for(seed: list[str]) -> list[str]:
    hints: list[str] = []
    for card in seed:
        hints.extend(_CARD_ARCHETYPE_HINTS.get(card, ()))
    detected = _detect_archetype(seed)
    if detected and detected != "Meta":
        hints.insert(0, detected)
    # Якоря архетипов, где seed пересекается с известными картами
    for arch, anchors in ARCHETYPE_ANCHORS.items():
        if set(seed) & anchors:
            hints.append(arch)
    # Уникальные с сохранением порядка
    out: list[str] = []
    for h in hints:
        if h not in out:
            out.append(h)
    if not out:
        out = ["Control", "Bridge Spam", "Beatdown", "Cycle"]
    return out


def _inject_seed_into_template(template_cards: list[str], seed: list[str]) -> list[str]:
    deck = list(template_cards)
    for card in seed:
        if card in deck:
            continue
        # Вытесняем не-win filler с конца
        replace_idx = None
        for i in range(len(deck) - 1, -1, -1):
            if deck[i] not in seed and deck[i] not in WIN_CONDITIONS:
                replace_idx = i
                break
        if replace_idx is None:
            replace_idx = len(deck) - 1
        deck[replace_idx] = card
    # unique preserve order, pad if needed
    uniq: list[str] = []
    for c in deck:
        if c not in uniq:
            uniq.append(c)
    return uniq[:8]


def _build_archetype_fallback(
    seed: list[str],
    pool: set[str],
    *,
    limit: int = 3,
) -> list[BuildResult]:
    db = get_database()
    pool = set(pool) | set(seed)
    results: list[BuildResult] = []
    seen: set[str] = set()

    for archetype in _archetype_candidates_for(seed):
        templates = [
            rec for rec in db.decks
            if rec.archetype == archetype and len(rec.cards) == 8
        ]
        templates.sort(key=lambda r: (-float(r.popularity or 0), r.id))
        for rec in templates[:12]:
            injected = _inject_seed_into_template(list(rec.cards), seed)
            if len(injected) != 8:
                continue
            # Finalize around seed as core
            from bot.services.deck_builder.builder import _finalize_deck

            trial = _finalize_deck(injected, seed, db, pool, archetype)
            if len(trial) != 8:
                continue
            key = "|".join(sorted(trial))
            if key in seen:
                continue
            seen.add(key)
            evaluation = DeckEvaluator.evaluate(
                trial, core=seed, archetype=archetype, db=db,
            )
            results.append(BuildResult(
                deck=trial,
                archetype=_candidate_archetype(trial, archetype),
                average_elixir=_avg_elixir(trial, db),
                confidence=30.0,
                source_deck_id=rec.id,
                balanced=evaluation.hard_constraints.passed,
                validation=None,
                evaluation=evaluation,
            ))
            if len(results) >= limit:
                return results

    results.sort(
        key=lambda r: -(r.evaluation.total_score if r.evaluation else 0),
    )
    return results[:limit]


def _meta_entries(seed: list[str], *, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in seed:
        for d in META_DECKS:
            if card not in d.cards:
                continue
            key = d.key
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "name": d.name,
                "key": d.key,
                "cards": list(d.cards),
                "category": d.category,
                "description": d.description,
            })
            if len(out) >= limit:
                return out
    return out


def build_decks_staged(
    seed_cards: list[str],
    *,
    arena_id: int | None = None,
    trophies: int | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Stage 1 meta → Stage 2 freeform → Stage 3 archetype. Всегда decks при валидных картах."""
    raw = [c.strip() for c in seed_cards if isinstance(c, str) and c.strip()]
    known = [c for c in raw if _card_known(c)]
    unknown = [c for c in raw if c not in known]

    if not known:
        return {
            "ok": False,
            "error_code": "BUILD_UNKNOWN_CARD",
            "error_params": {
                "card_ru": card_name_ru(unknown[0]) if unknown else "",
            },
            "core": raw,
            "decks": [],
            "stage": None,
            "mode": None,
        }

    pool = set(_get_arena_pool(arena_id, trophies))
    pool.update(known)
    db = get_database()
    pool.update(db.cards.keys())

    # --- Stage 1: curated meta templates ---
    meta = _meta_entries(known, limit=limit)
    if meta:
        return {
            "ok": True,
            "core": known,
            "decks": meta,
            "stage": STAGE_META,
            "mode": STAGE_META,
            "build_results": None,
        }

    # --- Stage 2: freeform around primary card ---
    expanded = _expand_seed_core(known, pool, db)
    freeform = _best_effort_from_core(expanded, pool, limit=limit)
    if freeform:
        return {
            "ok": True,
            "core": known,
            "decks": [],
            "stage": STAGE_FREEFORM,
            "mode": STAGE_FREEFORM,
            "build_results": freeform,
            "expanded_core": expanded,
        }

    # --- Stage 3: nearest archetype injection ---
    arch = _build_archetype_fallback(known, pool, limit=limit)
    if arch:
        return {
            "ok": True,
            "core": known,
            "decks": [],
            "stage": STAGE_ARCHETYPE,
            "mode": STAGE_ARCHETYPE,
            "build_results": arch,
            "expanded_core": known,
        }

    # Не должно случаться при known cards — последний отчаянный seed-only finalize
    from bot.services.deck_builder.builder import _finalize_deck, _required_role_seed
    from bot.services.deck_builder.constructor_decision import prepare_constructor_decision

    decision = prepare_constructor_decision(known[:4] or known, detect_archetype=_detect_archetype)
    seed8 = _finalize_deck(
        _required_role_seed(known[:4] or known, pool, db, decision),
        known[:4] or known,
        db,
        pool,
        decision.archetype,
    )
    if len(seed8) == 8:
        evaluation = DeckEvaluator.evaluate(
            seed8, core=known, archetype=decision.archetype, db=db,
        )
        last = BuildResult(
            deck=seed8,
            archetype=decision.archetype,
            average_elixir=_avg_elixir(seed8, db),
            confidence=20.0,
            source_deck_id=None,
            balanced=False,
            validation=None,
            evaluation=evaluation,
        )
        return {
            "ok": True,
            "core": known,
            "decks": [],
            "stage": STAGE_FREEFORM,
            "mode": STAGE_FREEFORM,
            "build_results": [last],
            "expanded_core": known,
        }

    logger.error("staged_build exhausted for seed=%s", known)
    return {
        "ok": False,
        "error_code": "BUILD_IMPOSSIBLE",
        "error_params": {"card_ru": card_name_ru(known[0])},
        "core": known,
        "decks": [],
        "stage": None,
        "mode": None,
    }
