"""Top Path of Legend players (global leaderboards) with current decks."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bot.config import settings
from bot.services.card_icons import (
    cards_from_team,
    deck_card_info_from_parsed,
    normalize_deck_upgrades,
    parse_battle_card,
)
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag

logger = logging.getLogger(__name__)

_refresh_lock = asyncio.Lock()
CACHE_VERSION = 5
DEFAULT_LIMIT = 10
_FETCH_CONCURRENCY = 5

_SKIP_BATTLE_TYPES = frozenset({
    "friendly", "clanmate", "warday", "boatbattle", "challenge", "tournament",
})

_LADDER_BATTLE_TYPES = frozenset({"pvp", "pathoflegend", "trail"})


@dataclass
class TopPlayersCache:
    players: list[dict] = field(default_factory=list)
    updated_at: datetime | None = None
    version: int = 0

    def expired(self) -> bool:
        if self.version != CACHE_VERSION:
            return True
        if self.updated_at is None:
            return True
        ttl = max(300, settings.meta_refresh_hours * 3600)
        return (datetime.now(timezone.utc) - self.updated_at).total_seconds() > ttl


_cache = TopPlayersCache()


def _deck_key(cards: list[dict]) -> frozenset[str]:
    return frozenset(c["name"] for c in cards if c.get("name"))


def _cards_from_current_deck(player: dict) -> list[dict]:
    raw = player.get("currentDeck") or []
    if len(raw) != 8:
        return []
    parsed = [parse_battle_card(c) for c in raw if c.get("name")]
    if len(parsed) != 8:
        return []
    for i, card in enumerate(parsed):
        card["slot"] = i
    return normalize_deck_upgrades(parsed)


def _latest_deck_from_battlelog(tag: str, battles: list) -> list[dict]:
    tag_norm = normalize_tag(tag)
    for battle in battles:
        team = battle.get("team", [{}])[0]
        if normalize_tag(team.get("tag") or "") != tag_norm:
            continue
        btype = (battle.get("type") or "").lower()
        if btype in _SKIP_BATTLE_TYPES:
            continue
        parsed = cards_from_team(team)
        if len(parsed) == 8:
            return parsed
    return []


def _deck_winrate(tag: str, battles: list, deck_key: frozenset[str]) -> tuple[int, int]:
    """Wins and losses on the given 8-card deck from recent ladder battles."""
    if len(deck_key) != 8:
        return 0, 0

    tag_norm = normalize_tag(tag)
    wins = losses = 0

    for battle in battles:
        team = battle.get("team", [{}])[0]
        if normalize_tag(team.get("tag") or "") != tag_norm:
            continue
        btype = (battle.get("type") or "").lower()
        if btype in _SKIP_BATTLE_TYPES or btype not in _LADDER_BATTLE_TYPES:
            continue

        parsed = cards_from_team(team)
        if len(parsed) != 8 or _deck_key(parsed) != deck_key:
            continue

        opponent = battle.get("opponent", [{}])[0]
        if team.get("crowns", 0) > opponent.get("crowns", 0):
            wins += 1
        else:
            losses += 1

    return wins, losses


async def _fetch_path_of_legend_rankings(client: ClashRoyaleClient, limit: int) -> list[dict]:
    """Global «Списки лидеров» — Path of Legend (most skilled players)."""
    paths = [
        f"/locations/global/pathoflegend/players?limit={limit}",
        f"/locations/57000249/pathoflegend/players?limit={limit}",
    ]
    for path in paths:
        try:
            data = await client._request(path)
            items = data.get("items", []) if isinstance(data, dict) else []
            if items:
                logger.info("Path of Legend rankings: %s (%d players)", path, len(items))
                return items[:limit]
        except ClashRoyaleAPIError as e:
            logger.debug("Path of Legend unavailable at %s: %s", path, e)
    return []


async def _build_player_entry(client: ClashRoyaleClient, item: dict) -> dict | None:
    tag = item.get("tag") or ""
    if not tag:
        return None

    name = item.get("name") or "Игрок"
    rank = int(item.get("rank") or 0)
    clan = item.get("clan") or {}
    clan_name = clan.get("name") or ""

    deck_cards: list[dict] = []
    trophies = 0
    wins = losses = 0

    try:
        player, battles = await asyncio.gather(
            client.get_player(tag),
            client.get_battlelog(tag),
        )
        trophies = int(player.get("trophies") or item.get("eloRating") or 0)
        deck_cards = _cards_from_current_deck(player)
        if not deck_cards:
            deck_cards = _latest_deck_from_battlelog(tag, battles)
        if deck_cards:
            wins, losses = _deck_winrate(tag, battles, _deck_key(deck_cards))
    except ClashRoyaleAPIError as e:
        logger.debug("Player data for %s: %s", tag, e)
        trophies = int(item.get("eloRating") or 0)

    if not deck_cards:
        return None

    deck_cards = normalize_deck_upgrades(deck_cards)
    names = [c["name"] for c in deck_cards]
    card_infos = [deck_card_info_from_parsed(c, slot=i) for i, c in enumerate(deck_cards)]
    elixirs = [c["cost"] for c in card_infos if c["cost"]]
    avg = round(sum(elixirs) / len(elixirs), 1) if elixirs else 0.0
    total = wins + losses
    wr = round(wins / total * 100, 1) if total else 0.0

    return {
        "rank": rank,
        "player_tag": tag.replace("#", ""),
        "player_name": name,
        "trophies": trophies,
        "clan_name": clan_name,
        "winrate": wr,
        "total_games": total,
        "avg_elixir": avg,
        "cards": card_infos,
        "deck_link": build_deck_share_link(names),
    }


async def _refresh_top_players(limit: int = DEFAULT_LIMIT) -> TopPlayersCache:
    await ensure_cards_loaded()
    client = ClashRoyaleClient()
    entries: list[dict] = []

    try:
        ranked = await _fetch_path_of_legend_rankings(client, limit)
        if not ranked:
            logger.warning("Path of Legend rankings empty")

        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def guarded(item: dict) -> dict | None:
            async with sem:
                return await _build_player_entry(client, item)

        results = await asyncio.gather(
            *[guarded(item) for item in ranked[:limit]],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, dict):
                entries.append(result)
            elif isinstance(result, Exception):
                logger.debug("Top player fetch error: %s", result)
    finally:
        await client.close()

    entries.sort(key=lambda p: p.get("rank", 999))
    if not entries:
        logger.warning("Top players cache empty after refresh")
    return TopPlayersCache(
        players=entries,
        updated_at=datetime.now(timezone.utc),
        version=CACHE_VERSION,
    )


async def get_top_players(*, limit: int = DEFAULT_LIMIT, force: bool = False) -> TopPlayersCache:
    global _cache
    if not force and not _cache.expired() and _cache.players:
        return _cache
    async with _refresh_lock:
        if not force and not _cache.expired() and _cache.players:
            return _cache
        _cache = await _refresh_top_players(limit=limit)
        return _cache
