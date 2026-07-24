"""Enriched public player preview for search / player page."""

from __future__ import annotations

import logging

from bot.services.card_icons import deck_card_info_from_parsed
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag
from bot.services.top_players import (
    _SKIP_BATTLE_TYPES,
    _LADDER_BATTLE_TYPES,
    _cards_from_current_deck,
    _deck_key,
    _deck_winrate,
    _latest_deck_from_battlelog,
)

logger = logging.getLogger(__name__)


def _lifetime_winrate(player: dict) -> tuple[float | None, int | None, int | None]:
    wins = player.get("wins")
    losses = player.get("losses")
    if wins is None or losses is None:
        return None, None, None
    wins_i = int(wins)
    losses_i = int(losses)
    total = wins_i + losses_i
    if total <= 0:
        return None, wins_i, losses_i
    return round(wins_i / total * 100, 1), wins_i, losses_i


def _recent_ladder_winrate(tag: str, battles: list) -> tuple[float | None, int]:
    tag_norm = normalize_tag(tag)
    wins = losses = 0
    for battle in battles:
        team = battle.get("team", [{}])[0]
        if normalize_tag(team.get("tag") or "") != tag_norm:
            continue
        btype = (battle.get("type") or "").lower()
        if btype in _SKIP_BATTLE_TYPES or btype not in _LADDER_BATTLE_TYPES:
            continue
        opponent = battle.get("opponent", [{}])[0]
        if team.get("crowns", 0) > opponent.get("crowns", 0):
            wins += 1
        else:
            losses += 1
    total = wins + losses
    if total <= 0:
        return None, 0
    return round(wins / total * 100, 1), total


def _arena_icon(arena: dict | None) -> str | None:
    if not isinstance(arena, dict):
        return None
    arena_id = arena.get("id")
    if arena_id is None:
        return None
    return f"https://royaleapi.github.io/cr-api-assets/arenas/small/{arena_id}.png"


def _favorite_card(player: dict) -> tuple[str | None, str | None, str | None]:
    """Returns avatar_url, favorite_card name, favorite_card_icon."""
    fav = player.get("currentFavouriteCard") or {}
    fav_icon: str | None = None
    fav_name: str | None = None
    if isinstance(fav, dict):
        fav_name = fav.get("name")
        icons = fav.get("iconUrls") or {}
        fav_icon = icons.get("medium") or icons.get("evolutionMedium") or icons.get("small")

    clan = player.get("clan") or {}
    badge_icon: str | None = None
    if isinstance(clan, dict):
        badges = clan.get("badgeUrls") or {}
        badge_icon = badges.get("medium") or badges.get("large")

    return fav_icon or badge_icon, fav_name, fav_icon


async def build_player_preview(tag: str) -> dict:
    """Build SearchResult-compatible dict with deck and winrate."""
    await ensure_cards_loaded()
    normalized = normalize_tag(tag)
    client = ClashRoyaleClient()
    try:
        player = await client.get_player(normalized)
        try:
            battles = await client.get_battlelog(normalized)
        except ClashRoyaleAPIError as e:
            logger.debug("Battlelog unavailable for preview %s: %s", normalized, e)
            battles = []
    finally:
        await client.close()

    arena = player.get("arena") or {}
    clan = player.get("clan") or {}
    avatar_url, favorite_card, favorite_card_icon = _favorite_card(player)
    winrate, total_wins, total_losses = _lifetime_winrate(player)
    recent_wr, recent_games = _recent_ladder_winrate(normalized, battles)
    if winrate is None and recent_wr is not None:
        winrate = recent_wr

    deck_cards = _cards_from_current_deck(player)
    if not deck_cards:
        deck_cards = _latest_deck_from_battlelog(normalized, battles)

    cards_payload: list[dict] = []
    avg_elixir = 0.0
    deck_link: str | None = None
    deck_winrate: float | None = None
    deck_games = 0

    if len(deck_cards) == 8:
        names = [c["name"] for c in deck_cards]
        cards_payload = [deck_card_info_from_parsed(c, slot=i) for i, c in enumerate(deck_cards)]
        elixirs = [int(c.get("cost") or 0) for c in cards_payload]
        avg_elixir = round(sum(elixirs) / len(elixirs), 1) if elixirs else 0.0
        deck_link = build_deck_share_link(names)
        wins, losses = _deck_winrate(normalized, battles, _deck_key(deck_cards))
        deck_games = wins + losses
        if deck_games:
            deck_winrate = round(wins / deck_games * 100, 1)

    return {
        "player_tag": normalized.replace("#", ""),
        "player_name": player.get("name", "Игрок"),
        "trophies": int(player.get("trophies") or 0),
        "arena": arena.get("name", "—") if isinstance(arena, dict) else "—",
        "arena_icon": _arena_icon(arena if isinstance(arena, dict) else None),
        "max_trophies": player.get("bestTrophies"),
        "clan_name": clan.get("name") if isinstance(clan, dict) else None,
        "exp_level": player.get("expLevel"),
        "winrate": winrate,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "recent_winrate": recent_wr,
        "recent_games": recent_games,
        "favorite_card": favorite_card,
        "favorite_card_icon": favorite_card_icon,
        "avatar_url": avatar_url,
        "cards": cards_payload,
        "avg_elixir": avg_elixir,
        "deck_link": deck_link,
        "deck_winrate": deck_winrate,
        "deck_games": deck_games,
    }
