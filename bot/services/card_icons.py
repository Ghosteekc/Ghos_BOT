"""Resolve card icons and evolution/hero state from API payloads."""

from __future__ import annotations

from bot.services.card_data import get_card_elixir
from bot.services.card_registry import get_card_info

MAX_EVOLUTIONS_PER_DECK = 2


def pick_icon_urls(icon_urls: dict | None, *, evolution_level: int = 0, hero_level: int = 0) -> str:
    icons = icon_urls or {}
    if hero_level >= 1 and icons.get("heroMedium"):
        return icons["heroMedium"]
    if evolution_level >= 1 and icons.get("evolutionMedium"):
        return icons["evolutionMedium"]
    return icons.get("medium") or icons.get("small") or ""


def parse_battle_card(card: dict) -> dict:
    """Parse a card object from battlelog or player deck."""
    icons = card.get("iconUrls") or {}
    hero = int(card.get("heroLevel") or 0)
    evo = int(card.get("evolutionLevel") or 0)
    if hero >= 1:
        evo = 0
    elif evo >= 1:
        hero = 0

    name = card.get("name") or ""
    info = get_card_info(name) if name else None
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
    return {
        "name": name,
        "icon": icon,
        "evolution_level": evo,
        "is_hero": hero >= 1,
        "cost": int(cost or 0),
        "slot": 0,
    }


def cards_from_team(team: dict) -> list[dict]:
    parsed = [parse_battle_card(c) for c in team.get("cards", []) if c.get("name")]
    for i, item in enumerate(parsed):
        item["slot"] = i
    return normalize_deck_upgrades(parsed)


def normalize_deck_upgrades(cards: list[dict]) -> list[dict]:
    """Game rules: max 2 evolutions; hero and evo are mutually exclusive per card."""
    result = [dict(c) for c in cards]
    for card in result:
        if card.get("is_hero"):
            card["evolution_level"] = 0
        _refresh_card_icon(card)

    evo_slots = [
        i for i, c in enumerate(result)
        if int(c.get("evolution_level") or 0) >= 1 and not c.get("is_hero")
    ]
    if len(evo_slots) > MAX_EVOLUTIONS_PER_DECK:
        for idx in evo_slots[MAX_EVOLUTIONS_PER_DECK:]:
            result[idx]["evolution_level"] = 0
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
    return {
        "id": f"{name.lower().replace(' ', '-')}-{slot_val}",
        "name": name,
        "icon": parsed.get("icon") or "",
        "cost": parsed.get("cost") or get_card_elixir(name),
        "evolution_level": parsed.get("evolution_level") or 0,
        "is_hero": bool(parsed.get("is_hero")),
        "slot": slot_val,
    }
