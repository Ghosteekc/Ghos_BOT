"""Сборка колод вокруг 4 выбранных карт — адаптер к deck_builder."""

from __future__ import annotations

from bot.services.card_icons import deck_card_info_from_parsed, normalize_deck_upgrades
from bot.services.card_matchups import calculate_deck_synergy
from bot.services.card_registry import build_deck_share_link, get_card_info
from bot.services.counter_engine import _get_arena_pool
from bot.services.deck_analyzer import analyze_deck
from bot.services.deck_builder import build_multiple_decks
from bot.services.meta_analyzer import _guess_category

_SLOT_EVO = {0, 2}
_SLOT_HERO = {1}


def slot_variant(slot_index: int, card_name: str) -> tuple[int, bool]:
    info = get_card_info(card_name) or {}
    max_evo = int(info.get("max_evolution_level") or 0)
    has_hero = bool(info.get("hero_icon"))
    if slot_index in _SLOT_HERO and has_hero:
        return 0, True
    if slot_index in _SLOT_EVO and max_evo >= 1:
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
    total = score_breakdown.get("total", 0) if score_breakdown else 0
    desc = f"Синергия {round(synergy_score, 0):.0f}% · баланс {round(total, 0):.0f} · эликсир {stats.avg_elixir}"

    return {
        "id": id_offset,
        "name": name,
        "cards": [deck_card_info_from_parsed(c, slot=i) for i, c in enumerate(out_parsed)],
        "synergy_score": round(synergy_score, 1),
        "total_score": round(total * 0.5 + synergy_score * 0.3 + confidence * 0.2, 1),
        "synergy_notes": synergy_notes[:4],
        "avg_elixir": stats.avg_elixir,
        "deck_link": build_deck_share_link(deck_names),
        "type": "constructor",
        "category": category,
        "description": desc,
        "archetype": archetype,
        "confidence": round(confidence, 1),
        "balanced": balanced,
        "score_breakdown": score_breakdown,
    }


def build_constructor_decks(
    slots: list[dict],
    arena_id: int | None = None,
    trophies: int | None = None,
    *,
    limit: int = 6,
) -> dict:
    core_parsed = _parsed_core_slots(slots)
    if len(core_parsed) != 4:
        return {"decks": [], "core": []}

    core_names = [c["name"] for c in core_parsed]
    pool = _get_arena_pool(arena_id, trophies)
    pool.update(core_names)

    built = build_multiple_decks(core_names, pool, limit=limit)
    decks: list[dict] = []
    deck_id = 7000

    for result in built:
        synergy_score, synergy_notes = calculate_deck_synergy(result.deck)
        entry = _build_deck_entry(
            core_parsed,
            result.deck,
            id_offset=deck_id,
            name="",
            archetype=result.archetype,
            confidence=result.confidence,
            synergy_score=synergy_score or result.synergy_score,
            synergy_notes=synergy_notes,
            balanced=result.balanced,
            score_breakdown=result.score_breakdown.as_dict() if result.score_breakdown else None,
        )
        if entry:
            decks.append(entry)
            deck_id += 1

    decks = _dedupe_constructor_entries(decks)
    decks.sort(key=lambda d: -d.get("total_score", 0))
    return {
        "core": [deck_card_info_from_parsed(c, slot=c.get("slot", i)) for i, c in enumerate(core_parsed)],
        "decks": decks[:limit],
    }
