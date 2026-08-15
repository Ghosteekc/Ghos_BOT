"""Многостадийная сборка колоды: meta → freeform → archetype.

Каждый кандидат проходит ``_validate_variant`` (Builder Validation).
Успешный ответ только если есть хотя бы одна stable-колода.
Иначе: status=NO_VALID_BUILD (ok=False) — без best-effort / last-resort.
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
from bot.services.meta_decks import META_DECKS

logger = logging.getLogger(__name__)

STAGE_META = "meta_templates"
STAGE_FREEFORM = "freeform_anchor"
STAGE_ARCHETYPE = "archetype_fallback"

STATUS_NO_VALID_BUILD = "NO_VALID_BUILD"
ERROR_NO_VALID_BUILD = "NO_VALID_BUILD"

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
    core = list(dict.fromkeys(seed))
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


def _core_present_in_deck(deck: list[str], seed: list[str]) -> list[str]:
    present = [c for c in seed if c in deck]
    return present or list(seed[:1])


def _validate_trial(
    trial: list[str],
    core: list[str],
    pool: set[str],
    *,
    archetype: str | None = None,
    confidence: float = 30.0,
    source_deck_id: int | None = None,
) -> BuildResult | None:
    """Прогнать кандидата через Builder Validation. None если FAILED."""
    if len(trial) != 8 or len(set(trial)) != 8:
        return None
    # Запрошенные карты ядра обязательны — иначе meta отдаёт «похожий» Hog 2.6
    # без Tornado / Electro Spirit и т.п.
    if core and not all(c in trial for c in core):
        return None
    db = get_database()
    core_in_deck = list(core) if core else _core_present_in_deck(trial, core)
    decision = prepare_constructor_decision(core_in_deck, detect_archetype=_detect_archetype)
    final_archetype = archetype or _candidate_archetype(trial, decision.archetype)
    primary_anchor = _core_primary_win(core_in_deck) or (core_in_deck[0] if core_in_deck else None)
    validation = _validate_variant(
        trial,
        core_in_deck,
        db,
        decision,
        archetype=final_archetype,
        primary_anchor=primary_anchor,
    )
    if not validation.stable:
        return None
    return BuildResult(
        deck=trial,
        archetype=final_archetype,
        average_elixir=_avg_elixir(trial, db),
        confidence=round(confidence, 1),
        source_deck_id=source_deck_id,
        balanced=True,
        validation=validation,
        evaluation=validation.evaluation,
    )


def _validated_builds_from_core(
    core: list[str],
    pool: set[str],
    *,
    limit: int = 3,
) -> list[BuildResult]:
    """Только stable-варианты (Validation PASSED)."""
    if len(core) in (3, 4):
        try:
            stable = build_multiple_decks(core, pool, limit=limit)
            if stable:
                # build_multiple_decks уже отфильтровал unstable
                return [r for r in stable if r.balanced and r.validation and r.validation.stable][:limit]
        except ValueError:
            pass

    db = get_database()
    pool = set(pool) | set(core)
    decision = prepare_constructor_decision(core, detect_archetype=_detect_archetype)
    primary_anchor = _core_primary_win(core) or core[0]

    candidates = _candidate_pool(core, db, pool, decision, primary_anchor)
    accepted: list[BuildResult] = []
    for trial, source, _reason in candidates:
        result = _validate_trial(
            trial,
            core,
            pool,
            archetype=_candidate_archetype(trial, decision.archetype),
            confidence=source.confidence if source else 28.0,
            source_deck_id=source.record.id if source else None,
        )
        if result is None:
            continue
        accepted.append(result)

    if not accepted:
        return []

    accepted.sort(key=lambda r: -_result_rank(r, decision))
    out: list[BuildResult] = []
    seen: set[str] = set()
    for item in accepted:
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
    for arch, anchors in ARCHETYPE_ANCHORS.items():
        if set(seed) & anchors:
            hints.append(arch)
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
        replace_idx = None
        for i in range(len(deck) - 1, -1, -1):
            if deck[i] not in seed and deck[i] not in WIN_CONDITIONS:
                replace_idx = i
                break
        if replace_idx is None:
            replace_idx = len(deck) - 1
        deck[replace_idx] = card
    uniq: list[str] = []
    for c in deck:
        if c not in uniq:
            uniq.append(c)
    return uniq[:8]


def _validated_archetype_builds(
    seed: list[str],
    pool: set[str],
    *,
    limit: int = 3,
) -> list[BuildResult]:
    """Архетипные кандидаты — только после Validation PASSED."""
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
            from bot.services.deck_builder.builder import _finalize_deck

            trial = _finalize_deck(injected, seed, db, pool, archetype)
            if len(trial) != 8:
                continue
            key = "|".join(sorted(trial))
            if key in seen:
                continue
            seen.add(key)
            result = _validate_trial(
                trial,
                seed,
                pool,
                archetype=archetype,
                confidence=30.0,
                source_deck_id=rec.id,
            )
            if result is None:
                continue
            results.append(result)
            if len(results) >= limit:
                return results

    results.sort(
        key=lambda r: -(r.evaluation.total_score if r.evaluation else 0),
    )
    return results[:limit]


def _meta_candidates(seed: list[str], *, limit: int) -> list[dict[str, Any]]:
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
            if len(out) >= limit * 4:
                return out
    return out


def _validated_meta_entries(
    seed: list[str],
    pool: set[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Curated meta — только если Validation PASSED и все seed-карты в колоде."""
    accepted: list[dict[str, Any]] = []
    for entry in _meta_candidates(seed, limit=max(limit * 4, 8)):
        cards = list(entry["cards"])
        if seed and not all(c in cards for c in seed):
            continue
        result = _validate_trial(cards, seed, pool, confidence=55.0)
        if result is None:
            continue
        accepted.append(entry)
        if len(accepted) >= limit:
            break
    return accepted


def _no_valid_build(known: list[str], *, last_issues: list[str] | None = None) -> dict[str, Any]:
    card = known[0] if known else ""
    card_ru = card_name_ru(card, short=True) if card else ""
    issue_hint = ", ".join(last_issues[:3]) if last_issues else ""
    reason = (
        f"Не удалось собрать стабильную колоду вокруг «{card_ru}»: "
        "ни один кандидат не прошёл проверку качества."
    )
    if issue_hint:
        reason = f"{reason} Типичные дыры: {issue_hint}."
    suggestion = (
        "Добавьте ещё 1–2 ключевые карты ядра (спелл / поддержку) "
        "или выберите другую главную угрозу."
    )
    return {
        "ok": False,
        "status": STATUS_NO_VALID_BUILD,
        "error_code": ERROR_NO_VALID_BUILD,
        "reason": reason,
        "suggestion": suggestion,
        "error_params": {
            "card_ru": card_ru,
            "reason": reason,
            "suggestion": suggestion,
        },
        "core": known,
        "decks": [],
        "stage": None,
        "mode": None,
        "build_results": None,
    }


def build_decks_staged(
    seed_cards: list[str],
    *,
    arena_id: int | None = None,
    trophies: int | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Stage 1 meta → Stage 2 freeform → Stage 3 archetype.

    Успех только при Validation PASSED. Иначе NO_VALID_BUILD.
    """
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

    # --- Stage 1: curated meta (только после Validation) ---
    meta = _validated_meta_entries(known, pool, limit=limit)
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
    freeform = _validated_builds_from_core(expanded, pool, limit=limit)
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
    arch = _validated_archetype_builds(known, pool, limit=limit)
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

    logger.info("staged_build NO_VALID_BUILD for seed=%s", known)
    return _no_valid_build(known)
