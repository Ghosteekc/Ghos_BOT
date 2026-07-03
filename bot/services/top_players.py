"""Top ladder players with current decks and recent winrate."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bot.config import settings
from bot.services.card_icons import cards_from_team, deck_card_info_from_parsed, normalize_deck_upgrades
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient
from bot.services.meta_analyzer import _current_season_id, _is_competitive_battle

logger = logging.getLogger(__name__)

_refresh_lock = asyncio.Lock()
CACHE_VERSION = 2


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
        ttl = max(30, settings.meta_refresh_hours * 60)
        return (datetime.now(timezone.utc) - self.updated_at).total_seconds() > ttl


_cache = TopPlayersCache()


async def _fetch_ranked_players(client: ClashRoyaleClient, limit: int) -> list[dict]:
    season = _current_season_id()
    paths = [
        f"/locations/global/pathoflegend/{season}/rankings/players?limit={limit}",
        f"/locations/57000006/pathoflegend/players?limit={limit}",
        f"/locations/57000249/pathoflegend/players?limit={limit}",
        f"/locations/57000193/pathoflegend/players?limit={limit}",
        f"/locations/57000249/rankings/players?limit={limit}",
    ]
    for path in paths:
        try:
            data = await client._request(path)
            items = data.get("items", []) if isinstance(data, dict) else []
            if items:
                return items
        except ClashRoyaleAPIError:
            continue
    return []


def _player_score(item: dict) -> int:
    return int(item.get("eloRating") or item.get("trophies") or 0)


async def _refresh_top_players(limit: int = 30) -> TopPlayersCache:
    await ensure_cards_loaded()
    client = ClashRoyaleClient()
    entries: list[dict] = []

    try:
        ranked = await _fetch_ranked_players(client, limit)
        for item in ranked[:limit]:
            tag = item.get("tag") or ""
            if not tag:
                continue
            name = item.get("name") or "Игрок"
            rank = int(item.get("rank") or len(entries) + 1)
            score = _player_score(item)
            clan = item.get("clan") or {}
            clan_name = clan.get("name") or ""

            deck_cards: list[dict] = []
            wins = losses = 0
            try:
                battles = await client.get_battlelog(tag)
                tag_norm = tag.upper()
                for battle in battles:
                    if not _is_competitive_battle(battle, tag_norm):
                        continue
                    team = battle.get("team", [{}])[0]
                    opponent = battle.get("opponent", [{}])[0]
                    if team.get("crowns", 0) > opponent.get("crowns", 0):
                        wins += 1
                    else:
                        losses += 1
                    if not deck_cards:
                        parsed = cards_from_team(team)
                        if len(parsed) == 8:
                            deck_cards = parsed
                await asyncio.sleep(0.12)
            except ClashRoyaleAPIError:
                pass

            if not deck_cards:
                continue

            deck_cards = normalize_deck_upgrades(deck_cards)
            names = [c["name"] for c in deck_cards]
            card_infos = [deck_card_info_from_parsed(c, slot=i) for i, c in enumerate(deck_cards)]
            elixirs = [c["cost"] for c in card_infos if c["cost"]]
            avg = round(sum(elixirs) / len(elixirs), 1) if elixirs else 0.0
            total = wins + losses
            wr = round(wins / total * 100, 1) if total else 0.0

            entries.append({
                "rank": rank,
                "player_tag": tag.replace("#", ""),
                "player_name": name,
                "trophies": score,
                "clan_name": clan_name,
                "winrate": wr,
                "total_games": total,
                "avg_elixir": avg,
                "cards": card_infos,
                "deck_link": build_deck_share_link(names),
            })
    finally:
        await client.close()

    entries.sort(key=lambda p: p.get("rank", 999))
    return TopPlayersCache(
        players=entries,
        updated_at=datetime.now(timezone.utc),
        version=CACHE_VERSION,
    )


async def get_top_players(*, limit: int = 30, force: bool = False) -> TopPlayersCache:
    global _cache
    if not force and not _cache.expired() and _cache.players:
        return _cache
    async with _refresh_lock:
        if not force and not _cache.expired() and _cache.players:
            return _cache
        _cache = await _refresh_top_players(limit=limit)
        return _cache
