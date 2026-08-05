"""Сборка колод вокруг 4 выбранных карт — адаптер к deck_builder.

Stage 1: полная сборка вокруг зафиксированного Core(4).
Stage 2 (fallback): Core Conflict Analysis — только если нет качественных колод.
"""

from __future__ import annotations

from bot.services.card_icons import deck_card_info_from_parsed, normalize_deck_upgrades
from bot.services.card_names_ru import card_name_ru
from bot.services.card_registry import build_deck_share_link, get_card_info
from bot.services.counter_engine import _get_arena_pool
from bot.services.deck_analyzer import analyze_deck
from bot.services.deck_builder import build_multiple_decks
from bot.services.deck_builder.balance import is_attack_win
from bot.services.deck_builder.core_conflict import (
    analyze_core_conflict,
    evaluation_score,
    filter_quality_results,
)
from bot.services.meta_analyzer import _guess_category

_SLOT_EVO = {0, 2}
_SLOT_HERO = {1}


def slot_variant(slot_index: int, card_name: str) -> tuple[int, bool]:
    """Resolve evo/hero for a constructor slot.

    ``maxEvolutionLevel`` alone is not enough: hero-only cards (Magic Archer,
    Giant, …) also have maxEvolutionLevel >= 1 but no ``evolutionMedium``.
    """
    info = get_card_info(card_name) or {}
    has_evo = bool(info.get("evolution_icon"))
    has_hero = bool(info.get("hero_icon"))
    if slot_index in _SLOT_HERO and has_hero:
        return 0, True
    if slot_index in _SLOT_EVO and has_evo:
        return 1, False
    return 0, False


def _parsed_core_slots(slots: list[dict]) -> list[dict]:
    parsed: list[dict] = []
    for item in sorted(slots, key=lambda x: int(x.get("slot", 0))):
        name = (item.get("name") or "").strip()
        if not name:
            continue
        slot_idx = int(item.get("slot", len(parsed)))
        evo, hero = slot_variant(slot_idx, name)
        info = get_card_info(name) or {}
        parsed.append({
            "name": name,
            "icon": info.get("icon") or "",
            "evolution_level": evo,
            "is_hero": hero,
            "cost": int(info.get("elixir") or 4),
            "slot": slot_idx,
        })
    return normalize_deck_upgrades(parsed)


def _category_from_archetype(archetype: str) -> str:
    mapping = {
        "Cycle": "cycle",
        "Log Bait": "bait",
        "Beatdown": "beatdown",
        "Control": "control",
        "Siege": "control",
        "Lava": "beatdown",
        "Royal Giant": "meta",
        "Bridge Spam": "meta",
        "Graveyard": "meta",
        "Fireball Bait": "bait",
        "Split Lane": "meta",
        "Meta": "meta",
    }
    return mapping.get(archetype, "meta")


def _deck_entry_key(entry: dict) -> str:
    names = [c.get("name") for c in entry.get("cards", []) if c.get("name")]
    return "|".join(sorted(names))


def _dedupe_constructor_entries(entries: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        key = _deck_entry_key(entry)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _build_deck_entry(
    core_parsed: list[dict],
    deck_names: list[str],
    *,
    id_offset: int,
    name: str,
    archetype: str,
    confidence: float,
    synergy_score: float,
    synergy_notes: list[str],
    balanced: bool = True,
    score_breakdown: dict | None = None,
    evaluation_report: dict | None = None,
    is_alternative: bool = False,
) -> dict | None:
    core_names = [c["name"] for c in core_parsed]
    if len(deck_names) != 8 or len(set(deck_names)) != 8:
        return None
    if not all(c in deck_names for c in core_names):
        return None

    filler_names = [c for c in deck_names if c not in core_names]
    out_parsed: list[dict] = []
    for p in sorted(core_parsed, key=lambda x: x.get("slot", 0)):
        out_parsed.append(dict(p))
    for i, name_card in enumerate(filler_names):
        info = get_card_info(name_card) or {}
        out_parsed.append({
            "name": name_card,
            "icon": info.get("icon") or "",
            "evolution_level": 0,
            "is_hero": False,
            "cost": int(info.get("elixir") or 4),
            "slot": len(core_parsed) + i,
        })

    out_parsed = normalize_deck_upgrades(out_parsed)
    for i, card in enumerate(out_parsed):
        card["slot"] = i

    stats = analyze_deck(deck_names)
    category = _category_from_archetype(archetype)
    # Единый total из EvaluationReport; score_breakdown — только API-compat.
    if evaluation_report and "total_score" in evaluation_report:
        total = float(evaluation_report["total_score"])
    elif score_breakdown:
        total = float(score_breakdown.get("total", 0) or 0)
    else:
        total = 0.0
    desc = f"Синергия {round(synergy_score, 0):.0f}% · баланс {round(total, 0):.0f} · эликсир {stats.avg_elixir}"
    if is_alternative:
        desc = "Альтернатива (ядро без конфликтующей карты) · " + desc

    return {
        "id": id_offset,
        "name": name,
        "cards": [deck_card_info_from_parsed(c, slot=i) for i, c in enumerate(out_parsed)],
        "synergy_score": round(synergy_score, 1),
        "total_score": round(total, 1),
        "synergy_notes": synergy_notes[:4],
        "avg_elixir": stats.avg_elixir,
        "deck_link": build_deck_share_link(deck_names),
        "type": "constructor_alt" if is_alternative else "constructor",
        "category": category,
        "description": desc,
        "archetype": archetype,
        "confidence": round(confidence, 1),
        "balanced": balanced,
        "score_breakdown": score_breakdown,  # Deprecated — заполняется из evaluation_report
        "evaluation_report": evaluation_report,
        "is_alternative": is_alternative,
    }


def _enrich_with_recommendation(
    entry: dict,
    deck_names: list[str],
    *,
    pool: set[str],
    archetype: str,
    builder_score: float | None,
    synergy_notes: list[str],
) -> dict:
    from bot.services.recommendation_engine import DeckOrigin, RecommendationEngine

    rec = RecommendationEngine.analyze(
        deck_names,
        pool=pool,
        apply_swaps=False,
        archetype=archetype,
        origin=DeckOrigin.BUILDER,
        builder_score=builder_score,
        synergy_notes=synergy_notes,
    )
    entry["improvements"] = []
    entry["game_plan"] = rec.game_plan.to_dict()
    entry["recommendation"] = rec.to_public_dict()
    if entry.get("evaluation_report") is None and rec.evaluation_report is not None:
        entry["evaluation_report"] = rec.evaluation_report.to_dict()
    if rec.sanity_report is not None:
        entry["sanity_report"] = rec.sanity_report.to_dict()
        if not rec.sanity_report.passed:
            entry["balanced"] = False
    return entry


def _score_breakdown_from_evaluation(report) -> dict:
    """Адаптер EvaluationReport → legacy score_breakdown для неизменного API."""
    details = report.matchup_coverage.details
    elixir_axis = report.elixir_profile.details.get(
        "axis_elixir",
        report.elixir_profile.score,
    )
    return {
        "synergy": round(report.synergy.score, 1),
        "offense": round(float(details.get("offense", 0.0)), 1),
        "defense": round(float(details.get("defense", 0.0)), 1),
        "anti_air": round(float(details.get("anti_air", 0.0)), 1),
        "anti_swarm": round(float(details.get("anti_swarm", 0.0)), 1),
        "spell_balance": round(report.spell_balance.score, 1),
        "elixir": round(float(elixir_axis), 1),
        "archetype_fit": round(report.archetype_fit.score, 1),
        "total": round(report.total_score, 1),
        "hard_issues": list(report.hard_constraints.issues),
        "soft_issues": list(report.soft_constraints.issues),
    }


def _entries_from_results(
    built,
    core_parsed: list[dict],
    pool: set[str],
    *,
    limit: int,
    id_start: int = 7000,
    is_alternative: bool = False,
) -> list[dict]:
    decks: list[dict] = []
    deck_id = id_start
    for result in built:
        if not any(is_attack_win(c) for c in result.deck):
            continue
        report = result.evaluation
        if report is None:
            continue
        # API-поля synergy_score / score_breakdown без изменений контракта —
        # заполняются из EvaluationReport (Builder больше их не отдаёт).
        synergy_score = float(report.synergy.score)
        synergy_notes = list(report.synergy.notes)
        builder_score = float(report.total_score)
        entry = _build_deck_entry(
            core_parsed,
            result.deck,
            id_offset=deck_id,
            name="",
            archetype=result.archetype,
            confidence=result.confidence,
            synergy_score=synergy_score,
            synergy_notes=synergy_notes,
            balanced=result.balanced,
            score_breakdown=_score_breakdown_from_evaluation(report),
            evaluation_report=report.to_dict(),
            is_alternative=is_alternative,
        )
        if entry:
            _enrich_with_recommendation(
                entry,
                result.deck,
                pool=pool,
                archetype=result.archetype,
                builder_score=builder_score,
                synergy_notes=synergy_notes,
            )
            decks.append(entry)
            deck_id += 1
        if len(decks) >= limit:
            break
    return _dedupe_constructor_entries(decks)


def build_constructor_decks(
    slots: list[dict],
    arena_id: int | None = None,
    trophies: int | None = None,
    *,
    limit: int = 6,
) -> dict:
    core_parsed = _parsed_core_slots(slots)
    empty = {
        "core": [],
        "decks": [],
        "core_conflict": None,
        "alternative_deck": None,
    }
    if len(core_parsed) != 4:
        return empty

    core_names = [c["name"] for c in core_parsed]
    pool = _get_arena_pool(arena_id, trophies)
    pool.update(core_names)

    # --- Stage 1: полная сборка вокруг зафиксированного Core(4) ---
    built = build_multiple_decks(core_names, pool, limit=limit)
    if not built:
        from bot.services.deck_builder.builder import build_deck_from_core

        try:
            built = [build_deck_from_core(core_names, pool=pool)]
        except ValueError:
            built = []

    quality = filter_quality_results(built)
    baseline_score = max((evaluation_score(r) for r in built), default=0.0)

    if quality:
        decks = _entries_from_results(quality, core_parsed, pool, limit=limit)
        decks.sort(key=lambda d: -d.get("total_score", 0))
        return {
            "core": [deck_card_info_from_parsed(c, slot=c.get("slot", i)) for i, c in enumerate(core_parsed)],
            "decks": decks[:limit],
            "core_conflict": None,
            "alternative_deck": None,
        }

    # --- Stage 2: Core Conflict Analysis (только fallback) ---
    conflict = analyze_core_conflict(
        core_names,
        pool=pool,
        baseline_score=baseline_score,
    )

    core_conflict_payload = None
    alternative_deck = None
    if conflict is not None:
        reduced_parsed = [c for c in core_parsed if c["name"] != conflict.conflicting_card]
        alt_entries = _entries_from_results(
            [conflict.alternative_result],
            reduced_parsed,
            pool,
            limit=1,
            id_start=7900,
            is_alternative=True,
        )
        if alt_entries:
            alternative_deck = alt_entries[0]
            core_conflict_payload = {
                "conflicting_card": conflict.conflicting_card,
                "conflicting_card_ru": card_name_ru(conflict.conflicting_card),
                "reason": conflict.reason,
                "baseline_score": conflict.baseline_score,
                "alternative_score": conflict.alternative_score,
                "quality_gain": conflict.quality_gain,
                "message": conflict.message,
                "drop_scores": conflict.drop_scores,
            }

    # Слабые Stage-1 сборки не отдаём как основную рекомендацию.
    return {
        "core": [deck_card_info_from_parsed(c, slot=c.get("slot", i)) for i, c in enumerate(core_parsed)],
        "decks": [],
        "core_conflict": core_conflict_payload,
        "alternative_deck": alternative_deck,
    }
