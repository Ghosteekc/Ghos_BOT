"""Player card collection and card mastery from Clash Royale API."""

from __future__ import annotations

import logging
import re

from bot.services.card_data import get_card_elixir
from bot.services.card_level import to_display_level, to_display_max_level
from bot.services.card_names_ru import card_name_ru
from bot.services.card_registry import ensure_cards_loaded, get_card_info, resolve_card_name

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _mastery_card_name(badge_name: str) -> str:
    resolved = resolve_card_name(badge_name.removeprefix("Mastery"))
    if resolved:
        return resolved
    raw = badge_name.removeprefix("Mastery")
    return re.sub(r"\s+", " ", re.sub(r"(?<!^)(?=[A-Z])", " ", raw)).strip()


def _card_display_mode(evo_level: int, owned: bool) -> str:
    if not owned:
        return "base"
    if evo_level == 1:
        return "evo"
    if evo_level == 2:
        return "hero"
    if evo_level >= 3:
        return "split"
    return "base"


def _resolve_icons(owned_raw: dict | None, info: dict) -> tuple[str, str, str]:
    icons = (owned_raw or {}).get("iconUrls") or {}
    base = icons.get("medium") or icons.get("small") or info.get("icon") or ""
    evo = icons.get("evolutionMedium") or info.get("evolution_icon") or base
    hero = icons.get("heroMedium") or info.get("hero_icon") or base
    return base, evo, hero


def _primary_icon(base: str, evo: str, hero: str, mode: str) -> str:
    if mode == "evo":
        return evo or base
    if mode == "hero":
        return hero or base
    if mode == "split":
        return evo or hero or base
    return base


def _mastery_next_hint(level: int, progress: int, target: int | None, max_level: int) -> str:
    if level >= max_level:
        return "Максимальный уровень мастерства"
    if target and target > progress:
        need = target - progress
        return f"Нужно ещё {need} очков мастерства — играйте этой картой в боях"
    return f"Продолжайте использовать карту для уровня {level + 1}"


_RARITY_COUNT_FIELDS = {
    "champion": "champion_count",
    "legendary": "legendary_count",
    "epic": "epic_count",
    "rare": "rare_count",
    "common": "common_count",
}


def build_collection_stats_from_entries(entries: list[dict]) -> dict:
    """Collection level, rarity counts, and cards grouped by in-game level."""
    owned = [e for e in entries if e.get("owned")]
    by_level: dict[int, int] = {}
    collection_level = 0
    evolution_count = 0
    hero_count = 0
    rarity_counts = {field: 0 for field in _RARITY_COUNT_FIELDS.values()}

    for card in owned:
        level = card.get("level")
        if level:
            collection_level += int(level)
            by_level[int(level)] = by_level.get(int(level), 0) + 1

        evo = int(card.get("evolution_level") or 0)
        if evo >= 1:
            evolution_count += 1
            collection_level += 5
        if evo >= 2:
            hero_count += 1
            collection_level += 5

        rarity = (card.get("rarity") or "").lower()
        field = _RARITY_COUNT_FIELDS.get(rarity)
        if field:
            rarity_counts[field] += 1

    cards_by_level = [
        {"level": level, "count": count}
        for level, count in sorted(by_level.items(), reverse=True)
    ]

    return {
        "collection_level": collection_level,
        "evolution_count": evolution_count,
        "hero_count": hero_count,
        "cards_by_level": cards_by_level,
        **rarity_counts,
    }


def build_collection_stats_from_player(player: dict) -> dict:
    """Lightweight collection stats from raw CR API player.cards."""
    rows: list[dict] = []
    for raw in player.get("cards") or []:
        rarity = (raw.get("rarity") or "").lower()
        api_level = raw.get("level")
        display = to_display_level(int(api_level) if api_level is not None else None, rarity)
        rows.append({
            "owned": True,
            "level": display,
            "rarity": rarity,
            "evolution_level": int(raw.get("evolutionLevel") or 0),
        })
    return build_collection_stats_from_entries(rows)


def _resolve_elixir(info: dict, owned_raw: dict | None, name: str) -> int | None:
    raw = info.get("elixir") or (owned_raw or {}).get("elixirCost")
    if raw is None:
        raw = get_card_elixir(name)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def build_player_collection(player: dict) -> dict:
    await ensure_cards_loaded()
    player_cards: dict[str, dict] = {}
    for raw in player.get("cards") or []:
        name = raw.get("name")
        if name:
            player_cards[_normalize_name(name)] = raw

    badges = player.get("badges") or []
    card_entries: list[dict] = []
    catalog = await ensure_cards_loaded()

    for info in sorted(catalog.values(), key=lambda x: x["name"]):
        name = info["name"]
        owned_raw = player_cards.get(_normalize_name(name))
        max_evo_catalog = int(info.get("max_evolution_level") or 0)

        if owned_raw:
            evo = int(owned_raw.get("evolutionLevel") or 0)
            max_evo = int(owned_raw.get("maxEvolutionLevel") or max_evo_catalog)
            base, icon_evo, icon_hero = _resolve_icons(owned_raw, info)
            mode = _card_display_mode(evo, True)
            level_raw = owned_raw.get("level")
            rarity = (owned_raw.get("rarity") or info.get("rarity") or "").lower()
            api_level = int(level_raw) if level_raw is not None else None
            api_max = int(owned_raw.get("maxLevel") or 0) or None
            elixir = _resolve_elixir(info, owned_raw, name)
            card_entries.append({
                "name": name,
                "name_ru": card_name_ru(name),
                "owned": True,
                "level": to_display_level(api_level, rarity),
                "max_level": to_display_max_level(api_max, rarity),
                "count": int(owned_raw.get("count") or 0),
                "rarity": rarity,
                "elixir": elixir,
                "evolution_level": evo,
                "max_evolution_level": max_evo,
                "display_mode": mode,
                "icon": _primary_icon(base, icon_evo, icon_hero, mode),
                "icon_base": base,
                "icon_evo": icon_evo,
                "icon_hero": icon_hero,
            })
        else:
            base = info.get("icon") or ""
            rarity = (info.get("rarity") or "").lower()
            elixir = _resolve_elixir(info, None, name)
            card_entries.append({
                "name": name,
                "name_ru": card_name_ru(name),
                "owned": False,
                "level": None,
                "max_level": to_display_max_level(info.get("max_level"), rarity),
                "count": 0,
                "rarity": rarity,
                "elixir": elixir,
                "evolution_level": 0,
                "max_evolution_level": max_evo_catalog,
                "display_mode": "base",
                "icon": base,
                "icon_base": base,
                "icon_evo": info.get("evolution_icon") or base,
                "icon_hero": info.get("hero_icon") or base,
            })

    mastery_entries: list[dict] = []
    for badge in badges:
        bname = badge.get("name") or ""
        if not bname.startswith("Mastery"):
            continue
        card_en = _mastery_card_name(bname)
        info = get_card_info(card_en) or {}
        owned_raw = player_cards.get(_normalize_name(card_en))
        base, icon_evo, icon_hero = _resolve_icons(owned_raw, info or {})
        evo = int((owned_raw or {}).get("evolutionLevel") or 0)
        mode = _card_display_mode(evo, owned_raw is not None)
        level = int(badge.get("level") or 0)
        max_level = int(badge.get("maxLevel") or 10)
        progress = int(badge.get("progress") or 0)
        target = badge.get("target")
        target_int = int(target) if target is not None else None
        pct = round(progress / target_int * 100, 1) if target_int and target_int > 0 else 100.0
        mastery_entries.append({
            "card_name": card_en,
            "card_name_ru": card_name_ru(card_en),
            "icon": _primary_icon(base, icon_evo, icon_hero, mode),
            "icon_base": base,
            "icon_evo": icon_evo,
            "icon_hero": icon_hero,
            "display_mode": mode,
            "level": level,
            "max_level": max_level,
            "progress": progress,
            "target": target_int,
            "progress_percent": min(100.0, pct),
            "next_hint": _mastery_next_hint(level, progress, target_int, max_level),
        })
    mastery_entries.sort(key=lambda x: (-x["level"], x["card_name_ru"]))

    owned_cards = sum(1 for c in card_entries if c["owned"])
    collection_stats = build_collection_stats_from_entries(card_entries)

    return {
        "cards": card_entries,
        "cards_owned": owned_cards,
        "cards_total": len(card_entries),
        "masteries": mastery_entries,
        **collection_stats,
    }
