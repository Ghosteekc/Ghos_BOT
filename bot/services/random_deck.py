"""Random 8-card deck generator (in-game style)."""

import random

from bot.services.card_data import CARD_META, get_card_elixir
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded, get_card_info

MAX_ATTEMPTS = 400
TARGET_AVG_MIN = 3.0
TARGET_AVG_MAX = 4.4

# Неигровые / без id в API — нельзя импортировать в Clash Royale
RANDOM_DECK_BLOCKLIST = frozenset({"Zombie"})


def _pack_deck(cards: list[str]) -> dict:
    elixirs = [get_card_elixir(c) for c in cards]
    avg = sum(elixirs) / len(elixirs)
    card_infos = []
    for name in cards:
        info = get_card_info(name) or {}
        card_infos.append({
            "name": name,
            "icon": info.get("icon", ""),
            "cost": int(info.get("elixir") or get_card_elixir(name)),
        })
    return {
        "cards": cards,
        "card_infos": card_infos,
        "avg_elixir": round(avg, 1),
        "deck_link": build_deck_share_link(cards),
    }


async def _playable_pool() -> list[str]:
    await ensure_cards_loaded()
    pool: list[str] = []
    for name in CARD_META:
        if name in RANDOM_DECK_BLOCKLIST:
            continue
        info = get_card_info(name)
        if not info or info.get("id") is None:
            continue
        if get_card_elixir(name) < 1:
            continue
        pool.append(name)
    return pool


async def generate_random_deck() -> dict:
    pool = await _playable_pool()
    if len(pool) < 8:
        raise ValueError("Not enough playable cards in catalog")

    for _ in range(MAX_ATTEMPTS):
        cards = random.sample(pool, 8)
        elixirs = [get_card_elixir(c) for c in cards]
        avg = sum(elixirs) / len(elixirs)
        if TARGET_AVG_MIN <= avg <= TARGET_AVG_MAX:
            packed = _pack_deck(cards)
            if packed.get("deck_link"):
                return packed

    for _ in range(MAX_ATTEMPTS):
        cards = random.sample(pool, 8)
        packed = _pack_deck(cards)
        if packed.get("deck_link"):
            return packed

    return _pack_deck(random.sample(pool, 8))
