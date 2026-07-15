"""Сборка колод вокруг 4 выбранных карт с учётом синергии и играбельности."""

from __future__ import annotations

from bot.services.card_data import WIN_CONDITIONS, get_card_elixir, get_card_role
from bot.services.card_icons import deck_card_info_from_parsed, normalize_deck_upgrades
from bot.services.card_matchups import calculate_deck_synergy, synergy_between, synergy_partners
from bot.services.card_registry import build_deck_share_link, get_card_info
from bot.services.counter_engine import _get_arena_pool
from bot.services.deck_analyzer import analyze_deck
from bot.services.meta_analyzer import _guess_category, _guess_deck_name

# Слоты 1 и 3 — эволюция, слот 2 — герой, слот 4 — обычная карта (индексы 0–3).
_SLOT_EVO = {0, 2}
_SLOT_HERO = {1}

_SPELL_PRIORITY = ("Zap", "The Log", "Fireball", "Arrows", "Poison", "Earthquake")
_CYCLE_FILL = ("Skeletons", "Ice Spirit", "Electro Spirit", "Bats", "Goblins")
_SUPPORT_FILL = ("Knight", "Musketeer", "Valkyrie", "Cannon", "Tesla", "Ice Golem")


def slot_variant(slot_index: int, card_name: str) -> tuple[int, bool]:
    """(evolution_level, is_hero) для ячейки конструктора."""
    info = get_card_info(card_name) or {}
    max_evo = int(info.get("max_evolution_level") or 0)
    has_hero = bool(info.get("hero_icon"))

    if slot_index in _SLOT_HERO and has_hero:
        return 0, True
    if slot_index in _SLOT_EVO and max_evo >= 1:
        return 1, False
    return 0, False


def _parsed_core_slots(slots: list[dict]) -> list[dict]:
    """slots: [{name, slot}, ...] — 4 уникальные карты."""
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
            "cost": int(info.get("elixir") or get_card_elixir(name)),
            "slot": slot_idx,
        })
    return normalize_deck_upgrades(parsed)


def _synergy_score(card: str, core: list[str]) -> float:
    score = 0.0
    for c in core:
        for src, dst in ((c, card), (card, c)):
            tier = synergy_between(src, dst)
            if tier == "strong":
                score += 3.0
            elif tier == "partial":
                score += 1.0
    return score


def _role_penalty(card: str, deck: list[str]) -> float:
    role = get_card_role(card)
    wins = sum(1 for c in deck if c in WIN_CONDITIONS or get_card_role(c) == "win_condition")
    spells = sum(1 for c in deck if get_card_role(c) == "spell")
    penalty = 0.0
    if card in WIN_CONDITIONS or role == "win_condition":
        penalty += 4.0 if wins >= 1 else 0.0
    if role == "spell":
        penalty += 2.0 if spells >= 2 else 0.0
    return penalty


def _rank_fillers(core: list[str], pool: set[str], *, prefer_cycle: bool = False) -> list[str]:
    candidates = [c for c in pool if c not in core]
    ranked = sorted(
        candidates,
        key=lambda c: (
            -_synergy_score(c, core),
            get_card_elixir(c) if prefer_cycle else 0,
            c,
        ),
    )
    for extra in _SPELL_PRIORITY + _CYCLE_FILL + _SUPPORT_FILL:
        if extra in pool and extra not in core and extra not in ranked:
            ranked.append(extra)
    return ranked


def _pick_fillers(core: list[str], pool: set[str], strategy: str) -> list[str]:
    prefer_cycle = strategy == "cycle"
    ranked = _rank_fillers(core, pool, prefer_cycle=prefer_cycle)
    deck = list(core)
    need = 8 - len(deck)

    if strategy == "spell":
        for spell in _SPELL_PRIORITY:
            if spell in pool and spell not in deck and get_card_role(spell) == "spell":
                deck.append(spell)
                break

    for card in ranked:
        if len(deck) >= 8:
            break
        if card in deck:
            continue
        if _role_penalty(card, deck) >= 4.0:
            continue
        deck.append(card)

    if not any(get_card_role(c) == "spell" for c in deck):
        for spell in _SPELL_PRIORITY:
            if spell not in pool or spell in deck:
                continue
            replaceable = [
                c for c in deck
                if c not in core and c not in WIN_CONDITIONS and get_card_role(c) != "win_condition"
            ]
            if replaceable:
                weakest = min(replaceable, key=lambda c: _synergy_score(c, core))
                deck[deck.index(weakest)] = spell
            elif len(deck) < 8:
                deck.append(spell)
            break

    while len(deck) < 8:
        added = False
        for card in ranked:
            if card not in deck:
                deck.append(card)
                added = True
                break
        if not added:
            break

    return deck[:8]


def _deck_playability_score(cards: list[str]) -> float:
    stats = analyze_deck(cards)
    score = 0.0
    if stats.spells:
        score += 12.0
    if stats.win_conditions:
        score += 8.0
    if stats.avg_elixir <= 4.0:
        score += 10.0
    elif stats.avg_elixir <= 4.4:
        score += 6.0
    elif stats.avg_elixir > 4.8:
        score -= 8.0
    return score


def _build_deck_entry(
    core_parsed: list[dict],
    filler_names: list[str],
    *,
    id_offset: int,
) -> dict | None:
    core_names = [c["name"] for c in core_parsed]
    if len(set(core_names)) != len(core_names):
        return None

    all_names = core_names + [c for c in filler_names if c not in core_names]
    if len(all_names) != 8 or len(set(all_names)) != 8:
        return None

    synergy_score, synergy_notes = calculate_deck_synergy(all_names)
    play_score = _deck_playability_score(all_names)
    total_score = synergy_score * 0.7 + play_score * 0.3

    filler_iter = [c for c in filler_names if c not in core_names]
    out_parsed: list[dict] = []
    for p in sorted(core_parsed, key=lambda x: x.get("slot", 0)):
        out_parsed.append(dict(p))
    for i, name in enumerate(filler_iter):
        info = get_card_info(name) or {}
        out_parsed.append({
            "name": name,
            "icon": info.get("icon") or "",
            "evolution_level": 0,
            "is_hero": False,
            "cost": int(info.get("elixir") or get_card_elixir(name)),
            "slot": len(core_parsed) + i,
        })

    out_parsed = normalize_deck_upgrades(out_parsed)
    for i, card in enumerate(out_parsed):
        card["slot"] = i

    card_infos = [deck_card_info_from_parsed(c, slot=i) for i, c in enumerate(out_parsed)]
    stats = analyze_deck(all_names)

    return {
        "id": id_offset,
        "name": _guess_deck_name(all_names),
        "cards": card_infos,
        "synergy_score": round(synergy_score, 1),
        "total_score": round(total_score, 1),
        "synergy_notes": synergy_notes[:4],
        "avg_elixir": stats.avg_elixir,
        "deck_link": build_deck_share_link(all_names),
        "type": "constructor",
        "category": _guess_category(all_names),
        "description": f"Синергия {synergy_score:.0f}% · ср. эликсир {stats.avg_elixir}",
    }


def build_constructor_decks(
    slots: list[dict],
    arena_id: int | None = None,
    trophies: int | None = None,
    *,
    limit: int = 6,
) -> dict:
    """Собрать варианты колод с 4 заданными картами."""
    core_parsed = _parsed_core_slots(slots)
    if len(core_parsed) != 4:
        return {"decks": [], "core": []}

    core_names = [c["name"] for c in core_parsed]
    pool = _get_arena_pool(arena_id, trophies)
    pool.update(core_names)

    strategies = ("synergy", "cycle", "spell", "balanced")
    seen: set[str] = set()
    decks: list[dict] = []
    deck_id = 7000

    for strategy in strategies:
        filler_deck = _pick_fillers(core_names, pool, strategy)
        key = "|".join(sorted(filler_deck))
        if key in seen or len(filler_deck) != 8:
            continue
        seen.add(key)
        entry = _build_deck_entry(
            core_parsed,
            filler_deck[len(core_names):],
            id_offset=deck_id,
        )
        if entry:
            decks.append(entry)
            deck_id += 1
        if len(decks) >= limit:
            break

    # Дополнительные варианты: топ синергичные пары от каждой core-карты
    if len(decks) < limit:
        partner_sets: list[list[str]] = []
        for name in core_names:
            strong, partial = synergy_partners(name, list(pool), limit=5)
            partners = strong + [p for p in partial if p not in strong]
            partner_sets.append([p for p in partners if p not in core_names][:3])

        for partners in partner_sets:
            if len(decks) >= limit:
                break
            extra = [p for group in partner_sets for p in group]
            ranked = _rank_fillers(core_names, pool)
            combo = list(core_names)
            for p in extra:
                if p not in combo and len(combo) < 8:
                    combo.append(p)
            for c in ranked:
                if len(combo) >= 8:
                    break
                if c not in combo:
                    combo.append(c)
            key = "|".join(sorted(combo))
            if key in seen or len(combo) != 8:
                continue
            seen.add(key)
            entry = _build_deck_entry(core_parsed, combo[len(core_names):], id_offset=deck_id)
            if entry:
                decks.append(entry)
                deck_id += 1

    decks.sort(key=lambda d: -d.get("total_score", 0))
    return {
        "core": [deck_card_info_from_parsed(c, slot=c.get("slot", i)) for i, c in enumerate(core_parsed)],
        "decks": decks[:limit],
    }
