"""Сборка колод вокруг 4 выбранных карт: классические мета-архетипы + умный добор."""

from __future__ import annotations

from bot.services.card_data import WIN_CONDITIONS, get_card_elixir, get_card_role
from bot.services.card_icons import deck_card_info_from_parsed, normalize_deck_upgrades
from bot.services.card_matchups import calculate_deck_synergy, synergy_between, synergy_partners
from bot.services.card_registry import build_deck_share_link, get_card_info
from bot.services.counter_engine import _get_arena_pool
from bot.services.deck_analyzer import analyze_deck
from bot.services.meta_analyzer import _guess_category, _guess_deck_name
from bot.services.meta_decks import META_DECKS, MetaDeck

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

_GENERIC_CARDS = {
    "Musketeer", "Fireball", "Zap", "The Log", "Ice Spirit", "Skeletons",
    "Ice Golem", "Knight", "Archers", "Cannon", "Arrows",
}

_HEAVY_WINS = {
    "Golem", "Lava Hound", "P.E.K.K.A", "Mega Knight", "Electro Giant",
    "Goblin Giant", "Elixir Golem", "Royal Giant", "Giant", "Sparky",
    "Three Musketeers", "Elite Barbarians",
}

_AIR_WINS = {"Lava Hound", "Balloon", "Goblin Giant"}

_WIN_TO_META: dict[str, list[str]] = {
    "Hog Rider": ["hog-26"],
    "Lava Hound": ["lava-loon"],
    "Golem": ["golem-nw"],
    "Goblin Barrel": ["log-bait"],
    "X-Bow": ["xbow-30"],
    "Mortar": ["mortar-cycle"],
    "Miner": ["miner-poison"],
    "Graveyard": ["graveyard"],
    "P.E.K.K.A": ["pekka-bs"],
    "Mega Knight": ["pekka-bs", "giant-dprince"],
    "Royal Giant": ["rg-fish", "ebarbs-rg"],
    "Giant": ["giant-dprince", "golem-nw"],
    "Balloon": ["lava-loon"],
    "Elixir Golem": ["giant-dprince", "ebarbs-rg"],
    "Electro Giant": ["pekka-bs"],
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


def _avg_elixir(cards: list[str]) -> float:
    if not cards:
        return 0.0
    return round(sum(get_card_elixir(c) for c in cards) / len(cards), 2)


def _core_profile(core: list[str]) -> dict:
    stats = analyze_deck(core)
    wins = [c for c in core if _is_win(c)]
    heavy = [c for c in core if c in _HEAVY_WINS or get_card_elixir(c) >= 5]
    air = [c for c in core if c in _AIR_WINS or get_card_role(c) == "air"]
    spells_in_core = [c for c in core if get_card_role(c) == "spell"]

    if wins and any(c in _AIR_WINS for c in wins + core):
        archetype = "beatdown_air"
    elif wins and any(c in _HEAVY_WINS for c in wins):
        archetype = "beatdown"
    elif stats.avg_elixir <= 3.4 and not heavy:
        archetype = "cycle"
    elif any(c in {"X-Bow", "Mortar"} for c in core):
        archetype = "control"
    elif any(c in {"Goblin Barrel", "Princess"} for c in core):
        archetype = "bait"
    else:
        archetype = "meta"

    return {
        "avg_elixir": stats.avg_elixir,
        "target_elixir": _target_deck_elixir(core),
        "wins": wins,
        "heavy": heavy,
        "air": air,
        "spells_in_core": spells_in_core,
        "archetype": archetype,
        "is_heavy": bool(heavy or any(w in _HEAVY_WINS for w in wins)),
    }


def _target_deck_elixir(core: list[str]) -> float:
    wins = [c for c in core if _is_win(c)]
    if wins:
        win_cost = max(get_card_elixir(w) for w in wins)
        if win_cost >= 7:
            return 4.2
        if win_cost >= 5:
            return 3.9
        if win_cost >= 4:
            return 3.5
    heavy_support = sum(1 for c in core if get_card_elixir(c) >= 4 and not _is_win(c))
    base = _avg_elixir(core)
    if heavy_support >= 2:
        return max(base + 0.6, 4.0)
    if heavy_support == 1:
        return max(base + 0.3, 3.6)
    return min(max(base + 0.4, 3.2), 3.8)


def _overlap_weight(core_set: set[str], meta: MetaDeck) -> float:
    score = 0.0
    for card in core_set & set(meta.cards):
        if card in _GENERIC_CARDS:
            score += 0.35
        elif _is_win(card):
            score += 5.0
        elif get_card_elixir(card) >= 4:
            score += 2.5
        else:
            score += 1.5
    for win in core_set:
        if win in _WIN_TO_META and meta.key in _WIN_TO_META[win]:
            score += 8.0
    return score


def _template_fits(core: list[str], meta: MetaDeck, profile: dict) -> bool:
    meta_avg = _avg_elixir(list(meta.cards))
    target = profile["target_elixir"]

    if meta.category == "cycle" and profile["is_heavy"]:
        return False
    if meta.category == "cycle" and target >= 3.9:
        return False
    if meta.category == "beatdown" and profile["archetype"] == "cycle" and not profile["is_heavy"]:
        return False
    if abs(meta_avg - target) > 1.1:
        return False

    overlap = _overlap_weight(set(core), meta)
    if set(core).issubset(set(meta.cards)):
        return True
    if overlap < 3.0:
        return False
    return True


def _score_template(core: list[str], meta: MetaDeck, profile: dict) -> float:
    if not _template_fits(core, meta, profile):
        return -1.0
    meta_avg = _avg_elixir(list(meta.cards))
    target = profile["target_elixir"]
    score = _overlap_weight(set(core), meta)
    if set(core).issubset(set(meta.cards)):
        score += 15.0
    score -= abs(meta_avg - target) * 4.0
    if meta.category == "beatdown" and profile["archetype"] in ("beatdown", "beatdown_air"):
        score += 4.0
    if meta.category == "cycle" and profile["archetype"] == "cycle":
        score += 4.0
    if meta.category == "bait" and profile["archetype"] == "bait":
        score += 4.0
    if meta.key == "hog-26" and "Hog Rider" not in core:
        score -= 6.0
    return score


def _rank_meta_templates(core: list[str]) -> list[MetaDeck]:
    profile = _core_profile(core)
    scored = [( _score_template(core, meta, profile), meta) for meta in META_DECKS]
    scored = [(s, m) for s, m in scored if s > 0]
    scored.sort(key=lambda x: (-x[0], x[1].name))
    return [m for _, m in scored]


def _spell_class(spell: str) -> str | None:
    if spell in _ANTI_SWARM_SPELLS:
        return "swarm"
    if spell in _FINISHER_SPELLS:
        return "finisher"
    if spell in _EXTRA_SPELLS:
        return "extra"
    return None


def _preferred_spells(core: list[str], template: MetaDeck | None) -> tuple[str, ...]:
    core_spells = [c for c in core if get_card_role(c) == "spell"]
    template_spells = (
        [c for c in template.cards if get_card_role(c) == "spell"]
        if template
        else []
    )
    order: list[str] = []
    for group in (core_spells, template_spells, _ANTI_SWARM_SPELLS, _FINISHER_SPELLS, _EXTRA_SPELLS):
        for spell in group:
            if spell not in order:
                order.append(spell)
    return tuple(order)


def _ensure_spells(
    deck: list[str],
    pool: set[str],
    core: list[str],
    template: MetaDeck | None = None,
) -> list[str]:
    out = list(deck)
    present_spells = [c for c in out if get_card_role(c) == "spell"]
    classes = {_spell_class(s) for s in present_spells}
    preferred = _preferred_spells(core, template)

    def _inject(spell: str) -> None:
        nonlocal out
        if spell not in pool or spell in out:
            return
        if not _can_add(spell, out):
            replaceable = [
                c for c in out
                if c not in core and c not in _is_win(c)
                and get_card_role(c) != "building"
                and (c in _GENERIC_CARDS or c in _CYCLE_CARDS)
            ]
            if replaceable:
                idx = out.index(min(replaceable, key=lambda c: _synergy_score(c, core)))
                out[idx] = spell
            return
        out.append(spell)

    if "swarm" not in classes:
        for spell in preferred:
            if _spell_class(spell) == "swarm":
                _inject(spell)
                break

    if "finisher" not in classes:
        for spell in preferred:
            if _spell_class(spell) == "finisher":
                _inject(spell)
                break

    if _role_counts(out)["spell"] < min(3, _MAX_SPELLS):
        for spell in preferred:
            if _spell_class(spell) == "extra" and _can_add(spell, out):
                _inject(spell)
                break

    return out[:8]


def _trim_excess(deck: list[str], core: list[str]) -> list[str]:
    out = list(deck)
    while len(out) > 8:
        drop = min(
            (c for c in out if c not in core),
            key=lambda c: (_synergy_score(c, core), -get_card_elixir(c)),
            default=None,
        )
        if drop is None:
            break
        out.remove(drop)

    while _role_counts(out)["win"] > _MAX_WIN:
        wins = [c for c in out if _is_win(c) and c not in core] or [c for c in out if _is_win(c)]
        if wins:
            out.remove(min(wins, key=lambda c: _synergy_score(c, core)))

    while _role_counts(out)["spell"] > _MAX_SPELLS:
        spells = [c for c in out if get_card_role(c) == "spell" and c not in core]
        if spells:
            out.remove(min(spells, key=lambda c: _synergy_score(c, core)))

    while _role_counts(out)["building"] > _MAX_BUILDINGS:
        buildings = [c for c in out if get_card_role(c) == "building" and c not in core]
        if buildings:
            out.remove(buildings[0])

    while _role_counts(out)["cycle"] > _MAX_CYCLE:
        cycles = [c for c in out if (c in _CYCLE_CARDS or get_card_role(c) == "cycle") and c not in core]
        if cycles:
            out.remove(cycles[0])

    return out


def _running_elixir_ok(deck: list[str], card: str, target: float) -> bool:
    trial = deck + [card]
    avg = _avg_elixir(trial)
    return abs(avg - target) <= 1.0


def _normalize_deck(
    cards: list[str],
    core: list[str],
    pool: set[str],
    template: MetaDeck | None = None,
    profile: dict | None = None,
) -> list[str] | None:
    profile = profile or _core_profile(core)
    unique = list(dict.fromkeys(cards))
    if len(unique) < len(core):
        return None
    out = unique[:8] if len(unique) >= 8 else list(unique)
    out = _trim_excess(out, core)
    out = _ensure_spells(out, pool, core, template)
    out = _trim_excess(out, core)

    target = profile["target_elixir"]
    ranked_pool = sorted(
        [c for c in pool if c not in out],
        key=lambda c: (-_synergy_score(c, core), -abs(get_card_elixir(c) - target)),
    )
    while len(out) < 8:
        added = False
        for card in ranked_pool:
            if card in out:
                continue
            if not _can_add(card, out):
                continue
            if not _running_elixir_ok(out, card, target) and card not in _GENERIC_CARDS:
                continue
            out.append(card)
            added = True
            break
        if not added:
            for card in ranked_pool:
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


def _deck_from_meta(meta: MetaDeck, core: list[str], pool: set[str], profile: dict) -> list[str] | None:
    core_set = set(core)
    if not core_set.issubset(set(meta.cards)):
        return None
    fillers = [c for c in meta.cards if c not in core_set]
    raw = core + fillers[: 8 - len(core)]
    return _normalize_deck(raw, core, pool, meta, profile)


def _complete_from_template(
    core: list[str],
    template: MetaDeck,
    pool: set[str],
    profile: dict,
) -> list[str] | None:
    if not _template_fits(core, template, profile):
        return None

    core_set = set(core)
    target = profile["target_elixir"]
    deck = list(core)

    template_fillers = [c for c in template.cards if c not in core_set and c in pool]
    ranked = sorted(
        template_fillers,
        key=lambda c: (
            -_synergy_score(c, core),
            -abs(get_card_elixir(c) - target),
        ),
    )
    for card in ranked:
        if len(deck) >= 8:
            break
        if not _can_add(card, deck):
            continue
        if profile["is_heavy"] and card in _CYCLE_CARDS and card not in template.cards[:4]:
            continue
        if _running_elixir_ok(deck, card, target) or card in template.cards:
            deck.append(card)

    if len(deck) < 8:
        deck = _fill_synergy_pool(deck, core, pool, profile, exclude=set(template.cards))

    return _normalize_deck(deck, core, pool, template, profile)


def _fill_synergy_pool(
    deck: list[str],
    core: list[str],
    pool: set[str],
    profile: dict,
    *,
    exclude: set[str] | None = None,
) -> list[str]:
    exclude = exclude or set()
    target = profile["target_elixir"]
    candidates: list[str] = []
    for card in core:
        strong, partial = synergy_partners(card, list(pool), limit=8)
        candidates.extend(strong + partial)

    ranked = sorted(
        dict.fromkeys(c for c in candidates if c not in deck and c in pool and c not in exclude),
        key=lambda c: (-_synergy_score(c, core), -abs(get_card_elixir(c) - target)),
    )
    out = list(deck)
    for card in ranked:
        if len(out) >= 8:
            break
        if _can_add(card, out) and (_running_elixir_ok(out, card, target) or profile["is_heavy"]):
            out.append(card)

    if len(out) < 8:
        extras = sorted(
            [c for c in pool if c not in out and c not in exclude],
            key=lambda c: (-_synergy_score(c, core), -abs(get_card_elixir(c) - target)),
        )
        for card in extras:
            if len(out) >= 8:
                break
            if _can_add(card, out):
                if profile["is_heavy"] and card in _CYCLE_CARDS and _synergy_score(card, core) < 2:
                    continue
                out.append(card)
    return out


def _playability_score(cards: list[str], profile: dict, *, meta_bonus: float = 0.0) -> float:
    stats = analyze_deck(cards)
    counts = _role_counts(cards)
    score = meta_bonus
    if stats.spells:
        score += 15.0
    if 1 <= counts["spell"] <= 3:
        score += 5.0
    if stats.win_conditions and counts["win"] <= _MAX_WIN:
        score += 10.0
    if counts["building"] <= 1:
        score += 5.0
    if counts["cycle"] <= _MAX_CYCLE:
        score += 5.0
    elif counts["cycle"] > 3:
        score -= 12.0
    score -= abs(stats.avg_elixir - profile["target_elixir"]) * 5.0
    return score


def _build_deck_entry(
    core_parsed: list[dict],
    deck_names: list[str],
    *,
    id_offset: int,
    meta: MetaDeck | None = None,
    profile: dict | None = None,
) -> dict | None:
    core_names = [c["name"] for c in core_parsed]
    profile = profile or _core_profile(core_names)
    if len(deck_names) != 8 or len(set(deck_names)) != 8:
        return None
    if not all(c in deck_names for c in core_names):
        return None

    synergy_score, synergy_notes = calculate_deck_synergy(deck_names)
    meta_bonus = 25.0 if meta and set(core_names).issubset(set(meta.cards)) else 8.0 if meta else 0.0
    play_score = _playability_score(deck_names, profile, meta_bonus=meta_bonus)
    total_score = synergy_score * 0.5 + play_score * 0.5

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
    if meta and not set(core_names).issubset(set(meta.cards)):
        deck_name = f"{meta.name} · под ваши карты"
    desc = meta.description if meta else f"Подбор под эликсир {stats.avg_elixir}"
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
    profile = _core_profile(core_names)

    seen: set[str] = set()
    decks: list[dict] = []
    deck_id = 7000
    templates = _rank_meta_templates(core_names)

    for meta in templates:
        if len(decks) >= limit:
            break
        built = _deck_from_meta(meta, core_names, pool, profile)
        if not built:
            built = _complete_from_template(core_names, meta, pool, profile)
        if not built:
            continue
        key = "|".join(sorted(built))
        if key in seen:
            continue
        seen.add(key)
        entry = _build_deck_entry(
            core_parsed, built, id_offset=deck_id, meta=meta, profile=profile,
        )
        if entry:
            decks.append(entry)
            deck_id += 1

    if len(decks) < limit:
        custom = _fill_synergy_pool(core_names, core_names, pool, profile)
        custom = _normalize_deck(custom, core_names, pool, profile=profile) if custom else None
        if custom:
            key = "|".join(sorted(custom))
            if key not in seen:
                seen.add(key)
                entry = _build_deck_entry(core_parsed, custom, id_offset=deck_id, profile=profile)
                if entry:
                    decks.append(entry)

    decks.sort(key=lambda d: -d.get("total_score", 0))
    return {
        "core": [deck_card_info_from_parsed(c, slot=c.get("slot", i)) for i, c in enumerate(core_parsed)],
        "decks": decks[:limit],
    }
