"""Resolve card icons and evolution/hero state from API payloads."""

from __future__ import annotations

from bot.services.card_data import get_card_elixir
from bot.services.card_registry import get_card_info

MAX_EVOLUTIONS_PER_DECK = 2
MAX_HEROES_PER_DECK = 2


def pick_icon_urls(icon_urls: dict | None, *, evolution_level: int = 0, hero_level: int = 0) -> str:
    icons = icon_urls or {}
    if hero_level >= 1 and icons.get("heroMedium"):
        return icons["heroMedium"]
    if evolution_level >= 1 and icons.get("evolutionMedium"):
        return icons["evolutionMedium"]
    return icons.get("medium") or icons.get("small") or ""


def _card_upgrade_icons(card: dict, info: dict | None) -> tuple[bool, bool]:
    """Whether this card can be a hero / evolution (from battle payload or catalog)."""
    icons = card.get("iconUrls") or {}
    has_hero = bool(icons.get("heroMedium") or (info or {}).get("hero_icon"))
    has_evo = bool(icons.get("evolutionMedium") or (info or {}).get("evolution_icon"))
    return has_hero, has_evo


def battle_card_modes(card: dict, info: dict | None = None) -> tuple[int, bool]:
    """Map official battlelog fields to (evolution_level, is_hero).

    Clash Royale battlelog does not send ``heroLevel``. Equipped upgrades use
    ``evolutionLevel`` with catalog icon hints:

    - evo-only (``evolutionMedium``): ``1`` = evolution equipped
    - hero-only (``heroMedium`` only, e.g. Giant / Dark Prince): ``2`` = hero
    - dual-path (both icons, ``maxEvolutionLevel`` 3): ``1`` = evo, ``2`` = hero
    - missing / ``0`` = base card (``heroMedium`` may still appear in iconUrls)
    """
    hero_explicit = int(card.get("heroLevel") or 0)
    if hero_explicit >= 1:
        return 0, True

    evo_raw = card.get("evolutionLevel")
    if evo_raw is None:
        return 0, False
    evo_val = int(evo_raw)
    if evo_val <= 0:
        return 0, False

    has_hero, has_evo = _card_upgrade_icons(card, info)

    if has_hero and not has_evo:
        # Hero-only cards (Giant, Dark Prince, Balloon, …)
        return 0, True
    if has_evo and not has_hero:
        return 1, False
    if has_hero and has_evo:
        if evo_val == 1:
            return 1, False
        if evo_val >= 2:
            return 0, True
        return 0, False

    # Fallback when icons are missing from payload/catalog
    max_evo = int(card.get("maxEvolutionLevel") or (info or {}).get("max_evolution_level") or 0)
    if max_evo >= 3:
        if evo_val == 1:
            return 1, False
        if evo_val >= 2:
            return 0, True
    if max_evo == 2 and evo_val >= 2:
        return 0, True
    if evo_val >= 1:
        return 1, False
    return 0, False


def parse_battle_card(card: dict) -> dict:
    """Parse a card object from battlelog or player deck."""
    from bot.services.card_level import to_display_level

    icons = card.get("iconUrls") or {}
    name = card.get("name") or ""
    info = get_card_info(name) if name else None
    evo, is_hero = battle_card_modes(card, info)
    hero = 1 if is_hero else 0
    rarity = (card.get("rarity") or (info.get("rarity") if info else "") or "common").lower()
    icon = pick_icon_urls(icons, evolution_level=evo, hero_level=hero)
    if evo < 1 and hero < 1:
        icon = icons.get("medium") or icons.get("small") or icon
    if not icon and info:
        reg_icons = {
            "medium": info.get("icon") or "",
            "evolutionMedium": info.get("evolution_icon") or "",
            "heroMedium": info.get("hero_icon") or "",
        }
        icon = pick_icon_urls(reg_icons, evolution_level=evo, hero_level=hero)
        if evo < 1 and hero < 1:
            icon = reg_icons["medium"] or icon
    cost = card.get("elixirCost") or (info.get("elixir") if info else None) or get_card_elixir(name)
    api_level = card.get("level")
    display_level = (
        to_display_level(int(api_level), rarity) if api_level is not None else None
    )
    return {
        "name": name,
        "icon": icon,
        "evolution_level": evo,
        "is_hero": is_hero,
        "cost": int(cost or 0),
        "rarity": rarity,
        "level": display_level,
        "slot": 0,
    }


def cards_from_team(team: dict) -> list[dict]:
    parsed = [parse_battle_card(c) for c in team.get("cards", []) if c.get("name")]
    for i, item in enumerate(parsed):
        item["slot"] = i
    return normalize_deck_upgrades(parsed)


def normalize_deck_upgrades(cards: list[dict]) -> list[dict]:
    """Game rules: max 2 evolutions and 2 heroes; hero and evo are mutually exclusive."""
    result = [dict(c) for c in cards]
    for card in result:
        if card.get("is_hero"):
            card["evolution_level"] = 0
        elif int(card.get("evolution_level") or 0) >= 1:
            card["is_hero"] = False
        _refresh_card_icon(card)

    evo_slots = [
        i for i, c in enumerate(result)
        if int(c.get("evolution_level") or 0) >= 1 and not c.get("is_hero")
    ]
    if len(evo_slots) > MAX_EVOLUTIONS_PER_DECK:
        for idx in evo_slots[MAX_EVOLUTIONS_PER_DECK:]:
            result[idx]["evolution_level"] = 0
            _refresh_card_icon(result[idx])

    hero_slots = [i for i, c in enumerate(result) if c.get("is_hero")]
    if len(hero_slots) > MAX_HEROES_PER_DECK:
        for idx in hero_slots[MAX_HEROES_PER_DECK:]:
            result[idx]["is_hero"] = False
            _refresh_card_icon(result[idx])
    return result


def _refresh_card_icon(card: dict) -> None:
    name = card.get("name") or ""
    evo = int(card.get("evolution_level") or 0)
    hero = 1 if card.get("is_hero") else 0
    info = get_card_info(name) or {}
    icons = {
        "medium": info.get("icon") or "",
        "evolutionMedium": info.get("evolution_icon") or "",
        "heroMedium": info.get("hero_icon") or "",
    }
    card["icon"] = pick_icon_urls(icons, evolution_level=evo, hero_level=hero)
    if evo < 1 and hero < 1:
        card["icon"] = icons["medium"] or card.get("icon") or ""


def deck_card_info_from_parsed(parsed: dict, *, slot: int | None = None) -> dict:
    name = parsed["name"]
    slot_val = slot if slot is not None else parsed.get("slot", 0)
    info = {
        "id": f"{name.lower().replace(' ', '-')}-{slot_val}",
        "name": name,
        "icon": parsed.get("icon") or "",
        "rarity": parsed.get("rarity") or "common",
        "cost": parsed.get("cost") or get_card_elixir(name),
        "evolution_level": parsed.get("evolution_level") or 0,
        "is_hero": bool(parsed.get("is_hero")),
        "slot": slot_val,
    }
    level = parsed.get("level")
    if level is not None:
        info["level"] = int(level)
    return info


def merge_deck_variants(variants: list[list[dict]]) -> list[dict]:
    """Pick the most common card order and evolution/hero per slot (as in-game)."""
    from collections import Counter

    if not variants:
        return []
    order_counts: Counter[tuple[str, ...]] = Counter()
    for variant in variants:
        order_counts[tuple(c["name"] for c in variant)] += 1
    best_order = order_counts.most_common(1)[0][0]
    matching = [v for v in variants if tuple(c["name"] for c in v) == best_order]
    # Prefer newest battle among matching order (variants are newest-first).
    base = matching[0] if matching else variants[0]
    merged: list[dict] = []
    for slot, card in enumerate(base):
        evo_votes: Counter[int] = Counter()
        hero_votes = 0
        for variant in matching:
            if slot >= len(variant):
                continue
            item = variant[slot]
            if item["name"] != card["name"]:
                continue
            if item.get("is_hero"):
                hero_votes += 1
            else:
                evo_votes[int(item.get("evolution_level") or 0)] += 1
        is_hero = hero_votes > len(matching) / 2
        best_evo = 0 if is_hero else (evo_votes.most_common(1)[0][0] if evo_votes else 0)
        parsed = {
            "name": card["name"],
            "icon": "",
            "evolution_level": best_evo,
            "is_hero": is_hero,
            "cost": card.get("cost") or get_card_elixir(card["name"]),
            "slot": slot,
        }
        if is_hero:
            parsed["evolution_level"] = 0
        _refresh_card_icon(parsed)
        merged.append(parsed)
    return normalize_deck_upgrades(merged)
