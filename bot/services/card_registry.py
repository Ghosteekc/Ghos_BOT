"""Cache Clash Royale cards: ids, icons, deck share links."""

import asyncio
import logging
import re
import time

from bot.config import settings
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient

logger = logging.getLogger(__name__)

_cards_by_name: dict[str, dict] | None = None
_refresh_lock = asyncio.Lock()
_next_refresh_at = 0.0
_REFRESH_SECONDS = 3600
_RETRY_SECONDS = 60

# CDN URLs from /cards API can 404 until Supercell publishes the asset.
_CARD_ICON_FALLBACKS: dict[str, str] = {}

# Evo / hero arts: official iconUrls often lag behind season drops.
# Paths are served from the webapp /public/cards.
_CARD_EVOLUTION_ICON_FALLBACKS: dict[str, str] = {
    "elite barbarians": "/cards/elite-barbarians-ev1.png",
}

_CARD_HERO_ICON_FALLBACKS: dict[str, str] = {
    "valkyrie": "/cards/valkyrie-hero.png",
    "berserker": "/cards/berserker-hero.png",
}

def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _webapp_asset(path: str) -> str:
    return f"{settings.webapp_url.rstrip('/')}{path}"


def _resolve_card_icon(name: str, api_icon: str) -> str:
    fallback_path = _CARD_ICON_FALLBACKS.get(_normalize_name(name))
    if fallback_path:
        return _webapp_asset(fallback_path)
    return api_icon


def _resolve_evolution_icon(name: str, api_icon: str) -> str:
    key = _normalize_name(name)
    fallback_path = _CARD_EVOLUTION_ICON_FALLBACKS.get(key)
    if fallback_path and not api_icon:
        return _webapp_asset(fallback_path)
    # Prefer local season art when API URL is present but often 404s on day-1.
    if fallback_path and key in _CARD_EVOLUTION_ICON_FALLBACKS:
        return _webapp_asset(fallback_path)
    return api_icon


def _resolve_hero_icon(name: str, api_icon: str) -> str:
    key = _normalize_name(name)
    fallback_path = _CARD_HERO_ICON_FALLBACKS.get(key)
    if fallback_path and not api_icon:
        return _webapp_asset(fallback_path)
    if fallback_path and key in _CARD_HERO_ICON_FALLBACKS:
        return _webapp_asset(fallback_path)
    return api_icon


def resolve_card_icon(name: str, api_icon: str) -> str:
    """Public wrapper for icon URL with CDN fallbacks."""
    return _resolve_card_icon(name, api_icon)


async def ensure_cards_loaded() -> dict[str, dict]:
    if _cards_by_name is not None:
        return _cards_by_name
    return await _refresh_cards()


async def _refresh_cards() -> dict[str, dict]:
    global _cards_by_name, _next_refresh_at
    async with _refresh_lock:
        if time.monotonic() < _next_refresh_at:
            return _cards_by_name or {}

        try:
            async with ClashRoyaleClient() as client:
                catalog = _parse_catalog(await client.get_cards())
        except (ClashRoyaleAPIError, ValueError, TypeError) as exc:
            _next_refresh_at = time.monotonic() + _RETRY_SECONDS
            logger.warning("Card catalog refresh failed (%s); keeping previous catalog", type(exc).__name__)
            return _cards_by_name or {}

        previous_by_id = {card["id"]: card for card in (_cards_by_name or {}).values()}
        changed = [card["name"] for card in catalog.values() if previous_by_id.get(card["id"]) != card]
        _cards_by_name = catalog
        _next_refresh_at = time.monotonic() + _REFRESH_SECONDS
        logger.info("Card catalog refreshed: %d cards, %d added or changed", len(catalog), len(changed))
        if previous_by_id and changed:
            logger.info("Updated cards: %s", ", ".join(changed))
        return catalog


async def run_periodic_card_refresh(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await _refresh_cards()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0, _next_refresh_at - time.monotonic()))
        except asyncio.TimeoutError:
            continue


def _parse_catalog(data: dict) -> dict[str, dict]:
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Card catalog has no items")
    cards_by_id: dict[int, dict] = {}
    names: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid card record")
        name = item.get("name")
        card_id = item.get("id")
        if not isinstance(name, str) or not name.strip() or type(card_id) is not int or card_id <= 0:
            raise ValueError("Invalid card identity")
        name = name.strip()
        key = _normalize_name(name)
        if card_id in cards_by_id or key in names:
            raise ValueError("Duplicate card identity")
        names.add(key)
        icons = item.get("iconUrls") or {}
        if not isinstance(icons, dict) or any(not isinstance(url, str) for url in icons.values() if url is not None):
            raise ValueError("Invalid card icons")
        api_icon = icons.get("medium") or icons.get("small") or ""
        evo_icon = _resolve_evolution_icon(name, icons.get("evolutionMedium") or "")
        hero_icon = _resolve_hero_icon(name, icons.get("heroMedium") or "")
        max_evo = int(item.get("maxEvolutionLevel") or 0)
        # The official cards API exposes an evolution variant through its
        # evolutionMedium art. Treat that API field as confirmation even when
        # maxEvolutionLevel is temporarily missing during a season rollout.
        has_evolution = bool(evo_icon or (max_evo >= (3 if hero_icon else 1)))
        if has_evolution:
            max_evo = max(max_evo, 1)
        # Dual-path (evo + hero): collection uses 1/2/3 evolutionLevel tiers.
        if has_evolution and hero_icon:
            max_evo = max(max_evo, 3)
        cards_by_id[card_id] = {
            "name": name,
            "id": card_id,
            "icon": _resolve_card_icon(name, api_icon),
            "evolution_icon": evo_icon,
            "hero_icon": hero_icon,
            "has_evolution": has_evolution,
            "max_evolution_level": max_evo,
            "elixir": item.get("elixirCost"),
            "rarity": item.get("rarity") or "",
            "max_level": int(item.get("maxLevel") or 0) or None,
        }
    return {_normalize_name(card["name"]): card for card in cards_by_id.values()}


def get_card_info(name: str) -> dict | None:
    if _cards_by_name is None:
        return None
    return _cards_by_name.get(_normalize_name(name))


def _compact_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


# Internal mastery badge suffixes differ from official card names in the CR API.
_MASTERY_SUFFIX_TO_CARD: dict[str, str] = {
    "Archer": "Archers",
    "Assassin": "Bandit",
    "AxeMan": "Executioner",
    "BarbLog": "Barbarian Barrel",
    "BlowdartGoblin": "Dart Goblin",
    "DartBarrell": "Dart Goblin",
    "ElixirCollector": "Elixir Collector",
    "FirespiritHut": "Furnace",
    "Ghost": "Royal Ghost",
    "GiantBuffer": "Royal Giant",
    "IceSpirits": "Ice Spirit",
    "Log": "The Log",
    "MergeMaiden": "Mother Witch",
    "MiniPekka": "Mini P.E.K.K.A",
    "Pekka": "P.E.K.K.A",
    "RageBarbarian": "Elite Barbarians",
    "SkeletonWarriors": "Skeletons",
    "Xbow": "X-Bow",
    "ZapMachine": "Zappies",
}


def resolve_card_name(raw: str) -> str | None:
    """Map mastery badge aliases and typos to a catalog card name."""
    if _cards_by_name is None:
        return None

    cleaned = re.sub(r"\s+", " ", raw.strip())
    suffix = cleaned.replace(" ", "")

    mapped = _MASTERY_SUFFIX_TO_CARD.get(suffix) or _MASTERY_SUFFIX_TO_CARD.get(cleaned)
    if mapped:
        info = get_card_info(mapped)
        if info:
            return info["name"]

    candidates = [
        cleaned,
        cleaned.replace(" ", ""),
        f"The {cleaned}",
        f"{cleaned}s",
    ]
    seen: set[str] = set()
    for cand in candidates:
        key = _normalize_name(cand)
        if key in seen:
            continue
        seen.add(key)
        info = get_card_info(cand)
        if info:
            return info["name"]

    compact = _compact_name(cleaned)
    if not compact:
        return None

    for norm, info in _cards_by_name.items():
        card_compact = _compact_name(info["name"])
        if compact == card_compact:
            return info["name"]
        if compact.endswith("s") and compact[:-1] == card_compact:
            return info["name"]
        if card_compact.endswith("s") and card_compact[:-1] == compact:
            return info["name"]

    return None


async def get_cards_catalog() -> list[dict]:
    from bot.services.card_names_ru import card_name_ru

    cards = await ensure_cards_loaded()
    catalog = []
    for info in cards.values():
        name = info["name"]
        catalog.append({
            "name": name,
            "name_ru": card_name_ru(name),
            "name_short": card_name_ru(name, short=True),
            "icon": info.get("icon") or "",
            "id": info.get("id"),
            "elixir": info.get("elixir"),
            "max_evolution_level": int(info.get("max_evolution_level") or 0),
            "has_hero": bool(info.get("hero_icon")),
            "icon_evo": info.get("evolution_icon") or "",
            "icon_hero": info.get("hero_icon") or "",
        })
    catalog.sort(key=lambda c: c["name"])
    return catalog


def build_deck_share_link(card_names: list[str]) -> str | None:
    """Supercell deck import link. None if any card id is unknown."""
    if _cards_by_name is None or len(card_names) != 8:
        return None
    ids: list[int] = []
    for name in card_names:
        info = get_card_info(name)
        if not info or info.get("id") is None:
            return None
        ids.append(int(info["id"]))
    return "https://link.clashroyale.com/deck/ru?deck=" + ";".join(str(i) for i in ids)
