"""Player card collection, emotes, and card mastery from Clash Royale API."""

from __future__ import annotations

import logging
import re

import aiohttp

from bot.services.card_icons import pick_icon_urls
from bot.services.card_names_ru import card_name_ru
from bot.services.card_registry import ensure_cards_loaded, get_card_info

logger = logging.getLogger(__name__)

EMOTES_CATALOG_URL = "https://royaleapi.github.io/cr-api-data/json/emotes.json"
_emotes_catalog_cache: list[dict] | None = None


def _mastery_card_name(badge_name: str) -> str:
    raw = badge_name.removeprefix("Mastery")
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", raw).strip()
    return spaced


def _evo_labels(evo_level: int, max_evo: int) -> tuple[bool, bool, bool]:
    has_evo = max_evo in (1, 3) or evo_level in (1, 3)
    has_hero = max_evo in (2, 3) or evo_level in (2, 3)
    both = evo_level == 3 or max_evo == 3
    return has_evo, has_hero, both


def _mastery_next_hint(level: int, progress: int, target: int | None, max_level: int) -> str:
    if level >= max_level:
        return "Максимальный уровень мастерства"
    if target and target > progress:
        need = target - progress
        return f"Нужно ещё {need} очков мастерства — играйте этой картой в боях"
    return f"Продолжайте использовать карту для уровня {level + 1}"


async def _load_emotes_catalog() -> list[dict]:
    global _emotes_catalog_cache
    if _emotes_catalog_cache is not None:
        return _emotes_catalog_cache

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(EMOTES_CATALOG_URL) as resp:
                if resp.status != 200:
                    logger.warning("Emotes catalog HTTP %s", resp.status)
                    _emotes_catalog_cache = []
                    return _emotes_catalog_cache
                data = await resp.json()
    except Exception as e:
        logger.warning("Failed to load emotes catalog: %s", e)
        _emotes_catalog_cache = []
        return _emotes_catalog_cache

    _emotes_catalog_cache = data if isinstance(data, list) else []
    return _emotes_catalog_cache


def _emote_label(entry: dict) -> str:
    sfx = entry.get("sfx_file") or ""
    base = sfx.split("/")[-1].replace(".ogg", "").replace("_01_dl", "").replace("_", " ")
    return base.title() if base else entry.get("name", "Emote")


def _estimate_emotes_owned(badge: dict | None, catalog_size: int) -> int:
    if not badge:
        return 0
    level = int(badge.get("level") or 0)
    progress = int(badge.get("progress") or 0)
    target = int(badge.get("target") or 100)
    if level <= 1:
        return min(catalog_size, progress)
    estimated = (level - 1) * target + progress
    return min(catalog_size, max(0, estimated))


async def build_player_collection(player: dict) -> dict:
    await ensure_cards_loaded()
    player_cards = {c.get("name"): c for c in (player.get("cards") or []) if c.get("name")}
    badges = player.get("badges") or []

    card_entries: list[dict] = []
    catalog = await ensure_cards_loaded()
    for info in sorted(catalog.values(), key=lambda x: x["name"]):
        name = info["name"]
        owned_raw = player_cards.get(name)
        max_evo_catalog = int(info.get("max_evolution_level") or 0)
        if owned_raw:
            evo = int(owned_raw.get("evolutionLevel") or 0)
            max_evo = int(owned_raw.get("maxEvolutionLevel") or max_evo_catalog)
            icons = owned_raw.get("iconUrls") or {}
            icon = pick_icon_urls(icons, evolution_level=evo if evo in (1, 3) else 0, hero_level=2 if evo == 2 else 0)
            if evo == 3:
                icon = pick_icon_urls(icons, evolution_level=1, hero_level=0) or icon
            if not icon:
                reg = {
                    "medium": info.get("icon") or "",
                    "evolutionMedium": info.get("evolution_icon") or "",
                    "heroMedium": info.get("hero_icon") or "",
                }
                icon = pick_icon_urls(reg, evolution_level=evo if evo in (1, 3) else 0, hero_level=2 if evo == 2 else 0)
            has_evo, has_hero, both = _evo_labels(evo, max_evo)
            card_entries.append({
                "name": name,
                "name_ru": card_name_ru(name),
                "owned": True,
                "level": int(owned_raw.get("level") or 0),
                "max_level": int(owned_raw.get("maxLevel") or 0),
                "count": int(owned_raw.get("count") or 0),
                "rarity": owned_raw.get("rarity") or "",
                "evolution_level": evo,
                "max_evolution_level": max_evo,
                "has_evo": has_evo,
                "has_hero": has_hero,
                "has_evo_and_hero": both,
                "icon": icon or info.get("icon") or "",
            })
        else:
            has_evo, has_hero, _ = _evo_labels(0, max_evo_catalog)
            card_entries.append({
                "name": name,
                "name_ru": card_name_ru(name),
                "owned": False,
                "level": None,
                "max_level": int(info.get("max_level") or 0) if info.get("max_level") else None,
                "count": 0,
                "rarity": "",
                "evolution_level": 0,
                "max_evolution_level": max_evo_catalog,
                "has_evo": has_evo,
                "has_hero": has_hero,
                "has_evo_and_hero": max_evo_catalog == 3,
                "icon": info.get("icon") or "",
            })

    emote_badge = next((b for b in badges if b.get("name") == "EmoteCollection"), None)
    emotes_catalog = await _load_emotes_catalog()
    owned_est = _estimate_emotes_owned(emote_badge, len(emotes_catalog))
    emote_entries: list[dict] = []
    for i, entry in enumerate(emotes_catalog):
        if not entry.get("available", True):
            continue
        default_owned = bool(entry.get("default_owned"))
        owned = default_owned or i < owned_est
        emote_entries.append({
            "id": entry.get("key") or entry.get("name") or str(i),
            "name": _emote_label(entry),
            "owned": owned,
            "exclusive": bool(entry.get("exclusive")),
            "icon": (emote_badge or {}).get("iconUrls", {}).get("large") if i == 0 and emote_badge else "",
        })

    mastery_entries: list[dict] = []
    for badge in badges:
        bname = badge.get("name") or ""
        if not bname.startswith("Mastery"):
            continue
        card_en = _mastery_card_name(bname)
        info = get_card_info(card_en) or get_card_info(card_en.replace(" ", ""))
        level = int(badge.get("level") or 0)
        max_level = int(badge.get("maxLevel") or 10)
        progress = int(badge.get("progress") or 0)
        target = badge.get("target")
        target_int = int(target) if target is not None else None
        pct = round(progress / target_int * 100, 1) if target_int and target_int > 0 else 100.0
        mastery_entries.append({
            "card_name": card_en,
            "card_name_ru": card_name_ru(card_en),
            "icon": (info or {}).get("icon") or badge.get("iconUrls", {}).get("large") or "",
            "level": level,
            "max_level": max_level,
            "progress": progress,
            "target": target_int,
            "progress_percent": min(100.0, pct),
            "next_hint": _mastery_next_hint(level, progress, target_int, max_level),
        })
    mastery_entries.sort(key=lambda x: (-x["level"], x["card_name_ru"]))

    owned_cards = sum(1 for c in card_entries if c["owned"])
    owned_emotes = sum(1 for e in emote_entries if e["owned"])

    return {
        "cards": card_entries,
        "cards_owned": owned_cards,
        "cards_total": len(card_entries),
        "emotes": emote_entries,
        "emotes_owned": owned_emotes,
        "emotes_total": len(emote_entries),
        "emote_collection_level": int(emote_badge.get("level") or 0) if emote_badge else 0,
        "emote_collection_progress": int(emote_badge.get("progress") or 0) if emote_badge else 0,
        "emote_collection_target": int(emote_badge.get("target") or 0) if emote_badge else None,
        "emotes_api_note": (
            "Supercell API не отдаёт эмодзи поштучно — полученные оцениваются по бейджу EmoteCollection."
            if emote_badge else None
        ),
        "masteries": mastery_entries,
    }
