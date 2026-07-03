"""Random 8-card deck generator (in-game style)."""

from __future__ import annotations

import random

from bot.services.card_data import CARD_META, get_card_elixir
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded, get_card_info
from bot.services.rofl_decks import ROFL_DECKS, RoflDeck

MAX_ATTEMPTS = 400
TARGET_AVG_MIN = 3.0
TARGET_AVG_MAX = 4.4

RANDOM_DECK_BLOCKLIST = frozenset({"Zombie"})

_valid_rofl_cache: list[tuple[RoflDeck, list[str]]] | None = None


def _pack_deck(
    cards: list[str],
    *,
    rofl_name: str | None = None,
    rofl_tagline: str | None = None,
    rofl_key: str | None = None,
) -> dict:
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
        "rofl": rofl_name is not None,
        "rofl_name": rofl_name,
        "rofl_tagline": rofl_tagline,
        "rofl_key": rofl_key,
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


async def _rofl_cards_valid(cards: tuple[str, ...]) -> list[str] | None:
    await ensure_cards_loaded()
    resolved: list[str] = []
    for card in cards:
        info = get_card_info(card)
        if info and info.get("id") is not None and card in CARD_META:
            resolved.append(card)
    if len(resolved) != 8:
        return None
    if build_deck_share_link(resolved) is None:
        return None
    return resolved


async def _valid_rofl_presets() -> list[tuple[RoflDeck, list[str]]]:
    global _valid_rofl_cache
    if _valid_rofl_cache is None:
        presets: list[tuple[RoflDeck, list[str]]] = []
        for preset in ROFL_DECKS:
            cards = await _rofl_cards_valid(preset.cards)
            if cards:
                presets.append((preset, cards))
        _valid_rofl_cache = presets
    return _valid_rofl_cache


async def generate_rofl_deck(*, exclude_key: str | None = None) -> dict:
    valid = await _valid_rofl_presets()
    if not valid:
        raise ValueError("Не удалось собрать рофл-колоду")

    pool = [(preset, cards) for preset, cards in valid if preset.key != exclude_key]
    if len(pool) < 2:
        pool = valid

    preset, cards = random.choice(pool)
    return _pack_deck(
        cards,
        rofl_name=preset.name,
        rofl_tagline=preset.tagline,
        rofl_key=preset.key,
    )


async def generate_random_deck(*, rofl: bool = False, exclude_key: str | None = None) -> dict:
    if rofl:
        return await generate_rofl_deck(exclude_key=exclude_key)

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
