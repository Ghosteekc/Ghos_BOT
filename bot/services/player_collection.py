"""Player card collection and card mastery from Clash Royale API."""

from __future__ import annotations

import logging
import re

from bot.services.card_names_ru import card_name_ru
from bot.services.card_registry import ensure_cards_loaded, get_card_info

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _mastery_card_name(badge_name: str) -> str:
    raw = badge_name.removeprefix("Mastery")
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", raw).strip()
    return spaced


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
            card_entries.append({
                "name": name,
                "name_ru": card_name_ru(name),
                "owned": True,
                "level": int(owned_raw.get("level") or 0) or None,
                "max_level": int(owned_raw.get("maxLevel") or 0) or None,
                "count": int(owned_raw.get("count") or 0),
                "rarity": owned_raw.get("rarity") or "",
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
            card_entries.append({
                "name": name,
                "name_ru": card_name_ru(name),
                "owned": False,
                "level": None,
                "max_level": None,
                "count": 0,
                "rarity": "",
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
        info = get_card_info(card_en) or get_card_info(card_en.replace(" ", ""))
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

    return {
        "cards": card_entries,
        "cards_owned": owned_cards,
        "cards_total": len(card_entries),
        "masteries": mastery_entries,
    }
