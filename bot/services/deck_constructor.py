"""Сборка колод вокруг 4 выбранных карт: классические мета-архетипы + умный добор."""

from __future__ import annotations

from bot.services.card_data import WIN_CONDITIONS, get_card_elixir, get_card_role
from bot.services.card_icons import deck_card_info_from_parsed, normalize_deck_upgrades
from bot.services.card_matchups import calculate_deck_synergy, synergy_between
from bot.services.card_registry import build_deck_share_link, get_card_info
from bot.services.counter_engine import _get_arena_pool
from bot.services.deck_analyzer import analyze_deck
from bot.services.meta_analyzer import _guess_category, _guess_deck_name
from bot.services.meta_decks import META_DECKS, MetaDeck

# Слоты 1 и 3 — эволюция, слот 2 — герой, слот 4 — обычная карта.
_SLOT_EVO = {0, 2}
_SLOT_HERO = {1}

_MAX_WIN = 1
_MAX_SPELLS = 3
_MAX_BUILDINGS = 1
_MAX_CYCLE = 2

_ANTI_SWARM_SPELLS = ("Zap", "The Log", "Arrows", "Barbarian Barrel", "Giant Snowball")
_FINISHER_SPELLS = ("Fireball", "Rocket", "Lightning")
_EXTRA_SPELLS = ("Poison", "Earthquake", "Freeze", "Tornado", "Rage")

_CYCLE_CARDS = {
    "Skeletons", "Ice Spirit", "Electro Spirit", "Fire Spirit", "Heal Spirit",
    "Bats", "Goblins", "Spear Goblins",
}


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
            "cost": int(info.get("elixir") or get_card_elixir(name)),
            "slot": slot_idx,
        })
    return normalize_deck_upgrades(parsed)


def _role_counts(deck: list[str]) -> dict[str, int]:
    return {
        "win": sum(1 for c in deck if c in WIN_CONDITIONS or get_card_role(c) == "win_condition"),
        "spell": sum(1 for c in deck if get_card_role(c) == "spell"),
        "building": sum(1 for c in deck if get_card_role(c) == "building"),
        "cycle": sum(1 for c in deck if c in _CYCLE_CARDS or get_card_role(c) == "cycle"),
    }


def _is_win(card: str) -> bool:
    return card in WIN_CONDITIONS or get_card_role(card) == "win_condition"


def _can_add(card: str, deck: list[str]) -> bool:
    if card in deck:
        return False
    counts = _role_counts(deck)
    role = get_card_role(card)
    if _is_win(card):
        return counts["win"] < _MAX_WIN
    if role == "spell":
        return counts["spell"] < _MAX_SPELLS
    if role == "building":
        return counts["building"] < _MAX_BUILDINGS
    if card in _CYCLE_CARDS or role == "cycle":
        return counts["cycle"] < _MAX_CYCLE
    return True


def _synergy_score(card: str, core: list[str]) -> float:
    score = 0.0
    for c in core:
        for a, b in ((c, card), (card, c)):
            tier = synergy_between(a, b)
            if tier == "strong":
                score += 3.0
            elif tier == "partial":
                score += 1.0
    return score


def _elixir_fit(card: str, target: float) -> float:
    return -abs(get_card_elixir(card) - target)


def _spell_class(spell: str) -> str | None:
    if spell in _ANTI_SWARM_SPELLS:
        return "swarm"
    if spell in _FINISHER_SPELLS:
        return "finisher"
    if spell in _EXTRA_SPELLS:
        return "extra"
    return None


def _ensure_spells(deck: list[str], pool: set[str], core: list[str]) -> list[str]:
    """Зап, бревно/аналог против мелочи + добиватель + до 3-го по необходимости."""
    out = list(deck)
    counts = _role_counts(out)
    present_spells = [c for c in out if get_card_role(c) == "spell"]
    classes = {_spell_class(s) for s in present_spells}

    def _inject(spell: str) -> None:
        nonlocal out
        if spell not in pool or spell in out:
            return
        if not _can_add(spell, out) and counts["spell"] >= _MAX_SPELLS:
            replaceable = [
                c for c in out
                if c not in core and get_card_role(c) == "spell"
                and _spell_class(c) == "extra"
            ]
            if not replaceable:
                replaceable = [
                    c for c in out
                    if c not in core and c not in WIN_CONDITIONS
                    and not _is_win(c) and get_card_role(c) != "building"
                ]
            if replaceable:
                idx = out.index(min(replaceable, key=lambda c: _synergy_score(c, core)))
                out[idx] = spell
            return
        if _can_add(spell, out):
            out.append(spell)

    if "swarm" not in classes:
        for spell in _ANTI_SWARM_SPELLS:
            if spell in pool:
                _inject(spell)
                break

    if "finisher" not in classes:
        for spell in _FINISHER_SPELLS:
            if spell in pool:
                _inject(spell)
                break

    counts = _role_counts(out)
    if counts["spell"] < _MAX_SPELLS and counts["spell"] < 3:
        stats = analyze_deck(out)
        if stats.avg_elixir >= 3.8:
            for spell in _EXTRA_SPELLS:
                if spell in pool:
                    _inject(spell)
                    if _role_counts(out)["spell"] >= min(3, _MAX_SPELLS):
                        break

    return out[:8]


def _trim_excess(deck: list[str], core: list[str]) -> list[str]:
    out = list(deck)
    while len(out) > 8:
        drop = min(
            (c for c in out if c not in core),
            key=lambda c: _synergy_score(c, core),
            default=None,
        )
        if drop is None:
            break
        out.remove(drop)

    while _role_counts(out)["win"] > _MAX_WIN:
        wins = [c for c in out if _is_win(c) and c not in core]
        if not wins:
            wins = [c for c in out if _is_win(c)]
        if wins:
            out.remove(min(wins, key=lambda c: _synergy_score(c, core)))

    while _role_counts(out)["spell"] > _MAX_SPELLS:
        spells = [c for c in out if get_card_role(c) == "spell" and c not in core]
        if not spells:
            break
        out.remove(min(spells, key=lambda c: _synergy_score(c, core)))

    while _role_counts(out)["building"] > _MAX_BUILDINGS:
        buildings = [c for c in out if get_card_role(c) == "building" and c not in core]
        if not buildings:
            break
        out.remove(buildings[0])

    while _role_counts(out)["cycle"] > _MAX_CYCLE:
        cycles = [c for c in out if (c in _CYCLE_CARDS or get_card_role(c) == "cycle") and c not in core]
        if not cycles:
            break
        out.remove(cycles[0])

    return out


def _normalize_deck(cards: list[str], core: list[str], pool: set[str]) -> list[str] | None:
    unique = list(dict.fromkeys(cards))
    if len(unique) < 8:
        return None
    out = unique[:8]
    out = _trim_excess(out, core)
    out = _ensure_spells(out, pool, core)
    out = _trim_excess(out, core)

    while len(out) < 8:
        added = False
        for card in pool:
            if card not in out and _can_add(card, out):
                out.append(card)
                added = True
                break
        if not added:
            break

    if len(out) != 8 or len(set(out)) != 8:
        return None
    if not all(c in out for c in core):
        return None
    return out


def _deck_from_meta(meta: MetaDeck, core: list[str], pool: set[str]) -> list[str] | None:
    core_set = set(core)
    if not core_set.issubset(set(meta.cards)):
        return None
    fillers = [c for c in meta.cards if c not in core_set]
    raw = core + fillers[: 8 - len(core)]
    return _normalize_deck(raw, core, pool)


def _best_meta_templates(core: list[str]) -> list[MetaDeck]:
    core_set = set(core)
    scored: list[tuple[float, MetaDeck]] = []
    for meta in META_DECKS:
        meta_set = set(meta.cards)
        overlap = len(core_set & meta_set)
        if overlap < 2:
            continue
        bonus = 10.0 if core_set.issubset(meta_set) else 0.0
        scored.append((overlap + bonus, meta))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    return [m for _, m in scored]


def _complete_from_template(
    core: list[str],
    template: MetaDeck,
    pool: set[str],
) -> list[str] | None:
    core_set = set(core)
    target_elixir = analyze_deck(core).avg_elixir
    deck = list(core)

    template_fillers = [c for c in template.cards if c not in core_set and c in pool]
    other = [c for c in pool if c not in core_set and c not in template_fillers]

    ranked = sorted(
        template_fillers,
        key=lambda c: (
            -_synergy_score(c, core),
            _elixir_fit(c, target_elixir),
        ),
    )
    for card in ranked:
        if len(deck) >= 8:
            break
        if _can_add(card, deck):
            deck.append(card)

    ranked_other = sorted(
        other,
        key=lambda c: (
            -_synergy_score(c, core),
            _elixir_fit(c, target_elixir),
        ),
    )
    for card in ranked_other:
        if len(deck) >= 8:
            break
        if _can_add(card, deck):
            deck.append(card)

    return _normalize_deck(deck, core, pool)


def _playability_score(cards: list[str], *, meta_bonus: float = 0.0) -> float:
    stats = analyze_deck(cards)
    counts = _role_counts(cards)
    score = meta_bonus
    if stats.spells:
        score += 15.0
    if 1 <= counts["spell"] <= 3:
        score += 5.0
    if stats.win_conditions and counts["win"] == 1:
        score += 10.0
    if counts["building"] <= 1:
        score += 5.0
    if counts["cycle"] <= 2:
        score += 5.0
    elif counts["cycle"] > 3:
        score -= 10.0
    if 3.0 <= stats.avg_elixir <= 4.4:
        score += 8.0
    elif stats.avg_elixir > 4.7:
        score -= 6.0
    return score


def _build_deck_entry(
    core_parsed: list[dict],
    deck_names: list[str],
    *,
    id_offset: int,
    meta: MetaDeck | None = None,
) -> dict | None:
    core_names = [c["name"] for c in core_parsed]
    if len(deck_names) != 8 or len(set(deck_names)) != 8:
        return None
    if not all(c in deck_names for c in core_names):
        return None

    synergy_score, synergy_notes = calculate_deck_synergy(deck_names)
    meta_bonus = 25.0 if meta and set(core_names).issubset(set(meta.cards)) else 0.0
    play_score = _playability_score(deck_names, meta_bonus=meta_bonus)
    total_score = synergy_score * 0.55 + play_score * 0.45

    filler_names = [c for c in deck_names if c not in core_names]
    out_parsed: list[dict] = []
    for p in sorted(core_parsed, key=lambda x: x.get("slot", 0)):
        out_parsed.append(dict(p))
    for i, name in enumerate(filler_names):
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

    stats = analyze_deck(deck_names)
    deck_name = meta.name if meta else _guess_deck_name(deck_names)
    category = meta.category if meta else _guess_category(deck_names)
    desc = meta.description if meta else f"Синергия {synergy_score:.0f}%"
    if meta:
        desc = f"{meta.description} · ср. эликсир {stats.avg_elixir}"

    return {
        "id": id_offset,
        "name": deck_name,
        "cards": [deck_card_info_from_parsed(c, slot=i) for i, c in enumerate(out_parsed)],
        "synergy_score": round(synergy_score, 1),
        "total_score": round(total_score, 1),
        "synergy_notes": synergy_notes[:4],
        "avg_elixir": stats.avg_elixir,
        "deck_link": build_deck_share_link(deck_names),
        "type": "constructor",
        "category": category,
        "description": desc,
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

    seen: set[str] = set()
    decks: list[dict] = []
    deck_id = 7000

    for meta in _best_meta_templates(core_names):
        if len(decks) >= limit:
            break
        built = _deck_from_meta(meta, core_names, pool)
        if not built:
            built = _complete_from_template(core_names, meta, pool)
        if not built:
            continue
        key = "|".join(sorted(built))
        if key in seen:
            continue
        seen.add(key)
        entry = _build_deck_entry(core_parsed, built, id_offset=deck_id, meta=meta)
        if entry:
            decks.append(entry)
            deck_id += 1

    templates = _best_meta_templates(core_names)
    extra_strategies = templates[:4] if templates else [None]
    for template in extra_strategies:
        if len(decks) >= limit:
            break
        if template is None:
            from bot.services.meta_decks import META_DECKS as ALL
            template = ALL[0]
        built = _complete_from_template(core_names, template, pool)
        if not built:
            continue
        key = "|".join(sorted(built))
        if key in seen:
            continue
        seen.add(key)
        is_classic = set(core_names).issubset(set(template.cards))
        entry = _build_deck_entry(
            core_parsed,
            built,
            id_offset=deck_id,
            meta=template if is_classic else None,
        )
        if entry:
            decks.append(entry)
            deck_id += 1

    decks.sort(key=lambda d: -d.get("total_score", 0))
    return {
        "core": [deck_card_info_from_parsed(c, slot=c.get("slot", i)) for i, c in enumerate(core_parsed)],
        "decks": decks[:limit],
    }
