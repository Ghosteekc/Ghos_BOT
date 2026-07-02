"""Cache Clash Royale cards: ids, icons, deck share links."""

import logging

from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient

logger = logging.getLogger(__name__)

_cards_by_name: dict[str, dict] | None = None


def _normalize_name(name: str) -> str:
    return name.strip().lower()


async def ensure_cards_loaded() -> dict[str, dict]:
    global _cards_by_name
    if _cards_by_name is not None:
        return _cards_by_name

    client = ClashRoyaleClient()
    try:
        data = await client.get_cards()
    except ClashRoyaleAPIError as e:
        logger.warning(f"Could not load cards list: {e}")
        _cards_by_name = {}
        return _cards_by_name
    finally:
        await client.close()

    result: dict[str, dict] = {}
    for item in data.get("items", []):
        name = item.get("name")
        if not name:
            continue
        icons = item.get("iconUrls") or {}
        result[_normalize_name(name)] = {
            "name": name,
            "id": item.get("id"),
            "icon": icons.get("medium") or icons.get("small") or "",
            "elixir": item.get("elixirCost"),
        }
    _cards_by_name = result
    logger.info(f"Card registry loaded: {len(result)} cards")
    return result


def get_card_info(name: str) -> dict | None:
    if _cards_by_name is None:
        return None
    return _cards_by_name.get(_normalize_name(name))


async def get_cards_catalog() -> list[dict]:
    from bot.services.card_names_ru import card_name_ru

    cards = await ensure_cards_loaded()
    catalog = []
    for info in cards.values():
        catalog.append({
            "name": info["name"],
            "name_ru": card_name_ru(info["name"]),
            "icon": info.get("icon") or "",
            "id": info.get("id"),
            "elixir": info.get("elixir"),
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
