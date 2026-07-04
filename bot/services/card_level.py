"""Convert Clash Royale API card levels to in-game display levels (1-16)."""

from __future__ import annotations

# API level + offset = level shown in game UI
RARITY_LEVEL_OFFSET: dict[str, int] = {
    "common": 0,
    "rare": 2,
    "epic": 5,
    "legendary": 8,
    "champion": 10,
}

RARITY_SORT_ORDER: dict[str, int] = {
    "champion": 0,
    "legendary": 1,
    "epic": 2,
    "rare": 3,
    "common": 4,
}


def to_display_level(api_level: int | None, rarity: str) -> int | None:
    if api_level is None:
        return None
    offset = RARITY_LEVEL_OFFSET.get((rarity or "").lower(), 0)
    return api_level + offset


def to_display_max_level(api_max: int | None, rarity: str) -> int | None:
    if api_max is None:
        return None
    offset = RARITY_LEVEL_OFFSET.get((rarity or "").lower(), 0)
    return api_max + offset
