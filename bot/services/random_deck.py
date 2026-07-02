"""Random 8-card deck generator (in-game style)."""

import random

from bot.services.card_data import CARD_META, get_card_elixir
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded, get_card_info

MAX_ATTEMPTS = 400
TARGET_AVG_MIN = 3.0
TARGET_AVG_MAX = 4.4


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


async def generate_random_deck() -> dict:
    await ensure_cards_loaded()
    pool = list(CARD_META.keys())
    if len(pool) < 8:
        raise ValueError("Not enough cards in catalog")

    for _ in range(MAX_ATTEMPTS):
        cards = random.sample(pool, 8)
        elixirs = [get_card_elixir(c) for c in cards]
        avg = sum(elixirs) / len(elixirs)
        if TARGET_AVG_MIN <= avg <= TARGET_AVG_MAX:
            return _pack_deck(cards)

    return _pack_deck(random.sample(pool, 8))
