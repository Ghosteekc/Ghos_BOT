"""Popular decks for the player's trophy bracket and arena."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bot.config import settings
from bot.services.card_data import get_card_elixir
from bot.services.card_icons import cards_from_team, deck_card_info_from_parsed, normalize_deck_upgrades
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded, get_card_info
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, encode_tag, normalize_tag
from bot.services.deck_analyzer import extract_deck
from bot.services.meta_analyzer import _guess_deck_name, _guess_category, _is_competitive_battle
from bot.services.meta_decks import META_DECKS
from bot.services.top_players import (
    _cards_from_current_deck,
    _deck_key,
    _deck_winrate,
    _latest_deck_from_battlelog,
)

logger = logging.getLogger(__name__)

_SCAN_CONCURRENCY = 6
_MAX_ARENA_PLAYERS = 36
_arena_refresh_lock = asyncio.Lock()


@dataclass
class _ArenaCacheEntry:
    data: dict
    updated_at: float
    version: int = 3

    def expired(self) -> bool:
        ttl = max(300, settings.meta_refresh_hours * 3600)
        return (time.time() - self.updated_at) > ttl


_arena_cache: dict[str, _ArenaCacheEntry] = {}


def _arena_cache_key(player_tag: str, trophies: int, arena_id: int | None) -> str:
    bucket = max(0, trophies // 250) * 250
    arena_part = str(arena_id) if arena_id is not None else "na"
    return f"{normalize_tag(player_tag)}:{arena_part}:{bucket}"


def _arena_trophy_band(trophies: int, arena_id: int | None) -> tuple[int, int]:
    """Approximate trophy window for the player's league / arena."""
    if trophies >= 9000:
        spread = 600
    elif trophies >= 7500:
        spread = 500
    elif trophies >= 5500:
        spread = 450
    elif trophies >= 4000:
        spread = 400
    else:
        spread = 350
    low = max(0, trophies - spread)
    high = trophies + spread
    if arena_id is not None and arena_id >= 54000000:
        low = max(low, 5000)
    return low, high


def _trophy_in_band(value: int, low: int, high: int) -> bool:
    if value <= 0:
        return True
    return low <= value <= high


def _cards_to_infos(cards: list[str], parsed: list[dict] | None = None) -> tuple[list[dict], float]:
    card_infos: list[dict] = []
    elixirs: list[float] = []
    if parsed and len(parsed) == 8:
        normalized = normalize_deck_upgrades(parsed)
        for slot, item in enumerate(normalized):
            card_infos.append(deck_card_info_from_parsed(item, slot=slot))
            elixirs.append(float(item.get("cost") or 0))
    else:
        for slot, name in enumerate(cards):
            info = get_card_info(name) or {}
            cost = float(info.get("elixir") or get_card_elixir(name))
            elixirs.append(cost)
            card_infos.append({
                "id": f"{name.lower().replace(' ', '-')}-{slot}",
                "name": name,
                "icon": info.get("icon") or "",
                "cost": int(cost),
                "evolution_level": 0,
                "is_hero": False,
                "slot": slot,
            })
    avg = round(sum(elixirs) / len(elixirs), 1) if elixirs else 0.0
    return card_infos, avg


async def _tags_from_player_clans(
    client: ClashRoyaleClient,
    player_tag: str,
    trophy_low: int,
    trophy_high: int,
    *,
    max_tags: int = 20,
) -> list[str]:
    """Other clan members in the same trophy band (not the user's personal opponents)."""
    exclude = normalize_tag(player_tag)
    found: list[str] = []
    seen: set[str] = {exclude}

    try:
        profile = await client.get_player(player_tag)
    except ClashRoyaleAPIError:
        return found

    clan_tag = (profile.get("clan") or {}).get("tag")
    if not clan_tag:
        return found

    try:
        data = await client._request(f"/clans/{encode_tag(clan_tag)}/members")
    except ClashRoyaleAPIError:
        return found

    for member in data.get("memberList") or []:
        tag = (member.get("tag") or "").upper()
        if not tag or tag in seen:
            continue
        member_trophies = int(member.get("trophies") or 0)
        if not _trophy_in_band(member_trophies, trophy_low, trophy_high):
            continue
        seen.add(tag)
        found.append(tag)
        if len(found) >= max_tags:
            break
    return found


async def _tags_from_rankings(
    client: ClashRoyaleClient,
    trophy_low: int,
    trophy_high: int,
    *,
    max_tags: int = 80,
) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    paths = [
        "/locations/global/rankings/players?limit=200",
        "/locations/57000006/rankings/players?limit=200",
        "/locations/57000249/rankings/players?limit=200",
    ]
    if trophy_high >= 9000:
        paths.insert(0, "/locations/global/pathoflegend/rankings/players?limit=200")

    for path in paths:
        try:
            data = await client._request(path)
        except ClashRoyaleAPIError as exc:
            logger.debug("Arena rankings %s: %s", path, exc)
            continue
        for item in data.get("items") or []:
            tag = (item.get("tag") or "").upper()
            if not tag or tag in seen:
                continue
            item_trophies = int(item.get("trophies") or 0)
            if not _trophy_in_band(item_trophies, trophy_low, trophy_high):
                continue
            seen.add(tag)
            tags.append(tag)
            if len(tags) >= max_tags:
                return tags
    return tags


async def _filter_tags_by_arena(
    client: ClashRoyaleClient,
    tags: list[str],
    arena_id: int | None,
    *,
    max_players: int = 25,
) -> list[str]:
    if arena_id is None or not tags:
        return tags[:max_players]

    sem = asyncio.Semaphore(_SCAN_CONCURRENCY)
    matched: list[str] = []

    async def check(tag: str) -> str | None:
        async with sem:
            try:
                player = await client.get_player(tag)
            except ClashRoyaleAPIError:
                return None
            player_arena = (player.get("arena") or {}).get("id")
            if player_arena == arena_id:
                return tag.upper()
            return None

    results = await asyncio.gather(*[check(tag) for tag in tags[:120]], return_exceptions=True)
    for result in results:
        if isinstance(result, str) and result not in matched:
            matched.append(result)
        if len(matched) >= max_players:
            break
    return matched


async def _discover_arena_player_tags(
    client: ClashRoyaleClient,
    player_tag: str,
    trophies: int,
    arena_id: int | None,
    *,
    max_players: int = _MAX_ARENA_PLAYERS,
) -> list[str]:
    """Sample of ladder players in the user's arena trophy band (not personal match history)."""
    trophy_low, trophy_high = _arena_trophy_band(trophies, arena_id)
    candidates: list[str] = []
    seen: set[str] = {normalize_tag(player_tag)}

    for tag in await _tags_from_rankings(client, trophy_low, trophy_high, max_tags=120):
        if tag not in seen:
            seen.add(tag)
            candidates.append(tag)

    for tag in await _tags_from_player_clans(
        client,
        player_tag,
        trophy_low,
        trophy_high,
        max_tags=24,
    ):
        if tag not in seen:
            seen.add(tag)
            candidates.append(tag)

    if arena_id is not None and candidates:
        arena_matched = await _filter_tags_by_arena(
            client,
            candidates,
            arena_id,
            max_players=max_players,
        )
        if arena_matched:
            return arena_matched

        extra: list[str] = []
        wide_low = max(0, trophy_low - 400)
        wide_high = trophy_high + 400
        for tag in await _tags_from_rankings(client, wide_low, wide_high, max_tags=160):
            if tag not in seen:
                seen.add(tag)
                extra.append(tag)
        arena_matched = await _filter_tags_by_arena(
            client,
            extra,
            arena_id,
            max_players=max_players,
        )
        if arena_matched:
            return arena_matched

    if candidates:
        return candidates[:max_players]

    # Wider trophy band if the ladder slice was empty (API limits).
    wide_low = max(0, trophy_low - 250)
    wide_high = trophy_high + 250
    for tag in await _tags_from_rankings(client, wide_low, wide_high, max_tags=80):
        if tag not in seen:
            seen.add(tag)
            candidates.append(tag)
    return candidates[:max_players]


async def _scan_player_tv_royale_deck(client: ClashRoyaleClient, tag: str) -> dict[str, dict]:
    """Current / latest deck of a player with ladder winrate on that deck."""
    try:
        player, battles = await asyncio.gather(
            client.get_player(tag),
            client.get_battlelog(tag),
        )
    except ClashRoyaleAPIError:
        return {}

    parsed = _cards_from_current_deck(player)
    if not parsed:
        parsed = _latest_deck_from_battlelog(tag, battles)
    if len(parsed) != 8:
        return {}

    cards = [c["name"] for c in parsed]
    key = "|".join(sorted(cards))
    wins, losses = _deck_winrate(tag, battles, _deck_key(parsed))
    total = wins + losses
    return {
        key: {
            "wins": wins,
            "total": total,
            "cards": cards,
            "variants": [parsed],
            "players": 1,
        },
    }


async def _scan_player_deck_stats(client: ClashRoyaleClient, tag: str) -> dict[str, dict]:
    """Deck winrates from a player's recent ladder battles."""
    deck_stats: dict[str, dict] = defaultdict(
        lambda: {"wins": 0, "total": 0, "cards": [], "variants": []},
    )
    try:
        battles = await client.get_battlelog(tag)
    except ClashRoyaleAPIError:
        return {}

    tag_norm = tag.upper()
    for battle in battles:
        if not _is_competitive_battle(battle, tag_norm):
            continue
        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        parsed = cards_from_team(team)
        if len(parsed) != 8:
            continue
        cards = [c["name"] for c in parsed]
        key = "|".join(sorted(cards))
        bucket = deck_stats[key]
        bucket["total"] += 1
        bucket["cards"] = cards
        bucket["variants"].append(parsed)
        if team.get("crowns", 0) > opponent.get("crowns", 0):
            bucket["wins"] += 1

    return deck_stats


def _merge_deck_stats(target: dict[str, dict], source: dict[str, dict]) -> None:
    for key, data in source.items():
        bucket = target[key]
        bucket["wins"] += data["wins"]
        bucket["total"] += data["total"]
        bucket["cards"] = data["cards"] or bucket["cards"]
        bucket["variants"].extend(data.get("variants") or [])
        bucket["players"] = int(bucket.get("players") or 0) + int(data.get("players") or 0)


def _stats_to_entries(deck_stats: dict[str, dict], *, id_base: int, min_games: int) -> list[dict]:
    ranked = []
    for data in deck_stats.values():
        total = int(data["total"])
        players = int(data.get("players") or 0)
        if total < min_games and players < 1:
            continue
        wr = round(data["wins"] / total * 100, 1) if total else 0.0
        ranked.append((wr, total, players, data))

    ranked.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    entries: list[dict] = []
    for i, (wr, total, players, data) in enumerate(ranked[:12]):
        cards = data["cards"]
        variant = data["variants"][0] if data.get("variants") else None
        card_infos, avg = _cards_to_infos(cards, variant)
        if total:
            desc = f"TV Royale · {players} игрок(ов) · {wr:.0f}% · {total} боёв"
        else:
            desc = f"TV Royale · {players} игрок(ов) · текущая колода"
        entries.append({
            "id": id_base + i,
            "name": _guess_deck_name(cards),
            "cards": card_infos,
            "winrate": wr,
            "total_games": total,
            "avg_elixir": avg,
            "type": "arena",
            "category": _guess_category(cards),
            "deck_link": build_deck_share_link(cards),
            "description": desc,
        })
    return entries


async def get_arena_popular_decks(
    battles: list,
    player_tag: str,
    trophies: int,
    arena_id: int | None,
    *,
    arena_name: str | None = None,
) -> dict:
    cache_key = _arena_cache_key(player_tag, trophies, arena_id)
    cached = _arena_cache.get(cache_key)
    if cached and not cached.expired():
        return cached.data

    async with _arena_refresh_lock:
        cached = _arena_cache.get(cache_key)
        if cached and not cached.expired():
            return cached.data
        data = await _build_arena_popular_decks(
            battles,
            player_tag,
            trophies,
            arena_id=arena_id,
            arena_name=arena_name,
        )
        _arena_cache[cache_key] = _ArenaCacheEntry(data=data, updated_at=time.time())
        return data


async def _build_arena_popular_decks(
    battles: list,
    player_tag: str,
    trophies: int,
    *,
    arena_id: int | None = None,
    arena_name: str | None = None,
) -> dict:
    await ensure_cards_loaded()

    combined_stats: dict[str, dict] = defaultdict(
        lambda: {"wins": 0, "total": 0, "cards": [], "variants": [], "players": 0},
    )

    client = ClashRoyaleClient()
    scanned = 0
    try:
        tags = await _discover_arena_player_tags(
            client,
            player_tag,
            trophies,
            arena_id,
        )
        sem = asyncio.Semaphore(_SCAN_CONCURRENCY)

        async def guarded(tag: str) -> dict[str, dict]:
            async with sem:
                return await _scan_player_tv_royale_deck(client, tag)

        results = await asyncio.gather(*[guarded(tag) for tag in tags], return_exceptions=True)
        for result in results:
            if isinstance(result, dict):
                _merge_deck_stats(combined_stats, result)
                scanned += 1
    finally:
        await client.close()

    entries = _stats_to_entries(combined_stats, id_base=4000, min_games=1)
    entries.sort(
        key=lambda e: (
            -(e.get("total_games") or 0),
            -(e.get("winrate") or 0),
        ),
    )

    has_live = bool(entries)
    if scanned > 0 and has_live:
        source = "tv_royale_arena"
    elif has_live:
        source = "tv_royale"
    else:
        source = "empty"

    if arena_name:
        display_arena = arena_name
    elif trophies >= 9000:
        display_arena = "Легендарная лига"
    elif trophies > 0:
        display_arena = "Ваша лига"
    else:
        display_arena = "Ваша арена"

    return {
        "arena_name": display_arena,
        "arena_id": arena_id,
        "trophies": trophies,
        "decks": entries[:12],
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def build_classic_meta_entries() -> tuple[list[dict], str | None, str]:
    """Static classic meta decks only (no live ladder scan)."""
    await ensure_cards_loaded()
    entries: list[dict] = []
    for i, meta in enumerate(META_DECKS):
        cards = list(meta.cards)
        card_infos, avg = _cards_to_infos(cards)
        entries.append({
            "id": 1000 + i,
            "name": meta.name,
            "cards": card_infos,
            "winrate": 0.0,
            "total_games": 0,
            "avg_elixir": avg,
            "type": "meta",
            "category": meta.category,
            "deck_link": build_deck_share_link(cards),
            "description": meta.description,
        })
    updated = datetime.now(timezone.utc).isoformat()
    return entries, updated, "classic"
