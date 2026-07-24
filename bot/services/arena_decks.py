"""Popular decks for the player's trophy bracket and arena."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.config import settings
from bot.services.card_data import get_card_elixir
from bot.services.card_icons import cards_from_team, deck_card_info_from_parsed, normalize_deck_upgrades
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded, get_card_info
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, encode_tag, normalize_tag
from bot.services.meta_analyzer import _guess_deck_name, _guess_category
from bot.services.meta_decks import META_DECKS
from bot.services.top_players import (
    _cards_from_current_deck,
    _deck_key,
    _deck_winrate,
    _latest_deck_from_battlelog,
)

logger = logging.getLogger(__name__)

_SCAN_CONCURRENCY = 6
_MAX_ARENA_PLAYERS = 28
_EMPTY_CACHE_TTL_SEC = 180
_ARENA_CACHE_VERSION = 4
_arena_refresh_lock = asyncio.Lock()


@dataclass
class _ArenaCacheEntry:
    data: dict
    updated_at: float
    version: int = _ARENA_CACHE_VERSION

    def expired(self) -> bool:
        if self.version != _ARENA_CACHE_VERSION:
            return True
        ttl = max(300, settings.meta_refresh_hours * 3600)
        if not (self.data.get("decks") or []):
            ttl = _EMPTY_CACHE_TTL_SEC
        return (time.time() - self.updated_at) > ttl


_arena_cache: dict[str, _ArenaCacheEntry] = {}


def _arena_cache_key(player_tag: str, trophies: int, arena_id: int | None) -> str:
    bucket = max(0, trophies // 250) * 250
    arena_part = str(arena_id) if arena_id is not None else "na"
    return f"{normalize_tag(player_tag)}:{arena_part}:{bucket}:v{_ARENA_CACHE_VERSION}"


def _arena_trophy_band(trophies: int, arena_id: int | None) -> tuple[int, int]:
    """Approximate trophy window for the player's league / arena."""
    if trophies >= 9000:
        spread = 700
    elif trophies >= 7500:
        spread = 550
    elif trophies >= 5500:
        spread = 500
    elif trophies >= 4000:
        spread = 450
    elif trophies >= 2000:
        spread = 400
    else:
        spread = 500
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


def _empty_stats_bucket() -> dict:
    return {"wins": 0, "total": 0, "cards": [], "variants": [], "players": 0}


def _opponent_tags_from_battles(
    battles: list,
    player_tag: str,
    *,
    arena_id: int | None = None,
    max_tags: int = 40,
) -> list[str]:
    """Opponents from recent battles — closest proxy to players on the same arena."""
    exclude = normalize_tag(player_tag)
    tags: list[str] = []
    seen: set[str] = {exclude}

    for battle in battles or []:
        if arena_id is not None:
            battle_arena = (battle.get("arena") or {}).get("id")
            if battle_arena is not None and battle_arena != arena_id:
                continue
        for opp in battle.get("opponent") or []:
            tag = (opp.get("tag") or "").upper()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
            if len(tags) >= max_tags:
                return tags
    return tags


def _seed_decks_from_battles(
    battles: list,
    player_tag: str,
    *,
    arena_id: int | None = None,
) -> dict[str, dict]:
    """Aggregate opponent decks seen in the user's recent battles (no extra API)."""
    exclude = normalize_tag(player_tag)
    deck_stats: dict[str, dict] = defaultdict(_empty_stats_bucket)

    for battle in battles or []:
        if arena_id is not None:
            battle_arena = (battle.get("arena") or {}).get("id")
            if battle_arena is not None and battle_arena != arena_id:
                continue

        team = (battle.get("team") or [{}])[0]
        team_tag = normalize_tag(team.get("tag") or "")
        # Prefer battles where the linked player is on the team side.
        if team_tag and team_tag != exclude:
            continue

        for opp in battle.get("opponent") or []:
            parsed = cards_from_team(opp)
            if len(parsed) != 8:
                continue
            cards = [c["name"] for c in parsed]
            key = "|".join(sorted(cards))
            bucket = deck_stats[key]
            bucket["total"] += 1
            bucket["cards"] = cards
            bucket["variants"].append(parsed)
            bucket["players"] = max(int(bucket.get("players") or 0), 1)
            # Opponent won against user → that deck "won" this sample game.
            if opp.get("crowns", 0) > team.get("crowns", 0):
                bucket["wins"] += 1

    return deck_stats


async def _tags_from_player_clans(
    client: ClashRoyaleClient,
    player_tag: str,
    trophy_low: int,
    trophy_high: int,
    *,
    max_tags: int = 24,
) -> list[str]:
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
        if member_trophies > 0 and not _trophy_in_band(member_trophies, trophy_low, trophy_high):
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


async def _prefer_same_arena(
    client: ClashRoyaleClient,
    tags: list[str],
    arena_id: int | None,
    *,
    max_players: int,
    min_keep: int = 8,
) -> list[str]:
    """Prefer players on the exact arena, but keep trophy-band tags if too few match."""
    if arena_id is None or not tags:
        return tags[:max_players]

    sem = asyncio.Semaphore(_SCAN_CONCURRENCY)
    matched: list[str] = []
    unmatched: list[str] = []

    async def check(tag: str) -> tuple[str, bool]:
        async with sem:
            try:
                player = await client.get_player(tag)
            except ClashRoyaleAPIError:
                return tag, False
            player_arena = (player.get("arena") or {}).get("id")
            return tag, player_arena == arena_id

    results = await asyncio.gather(*[check(tag) for tag in tags[:max_players * 3]], return_exceptions=True)
    for result in results:
        if not isinstance(result, tuple):
            continue
        tag, ok = result
        if ok:
            if tag not in matched:
                matched.append(tag)
        elif tag not in unmatched and tag not in matched:
            unmatched.append(tag)
        if len(matched) >= max_players:
            break

    if len(matched) >= min_keep:
        return matched[:max_players]

    merged = matched + [t for t in unmatched if t not in matched]
    return merged[:max_players]


async def _discover_arena_player_tags(
    client: ClashRoyaleClient,
    player_tag: str,
    trophies: int,
    arena_id: int | None,
    battles: list,
    *,
    max_players: int = _MAX_ARENA_PLAYERS,
) -> list[str]:
    """Build a player sample: battle opponents first, then clan / rankings."""
    trophy_low, trophy_high = _arena_trophy_band(trophies, arena_id)
    candidates: list[str] = []
    seen: set[str] = {normalize_tag(player_tag)}

    for tag in _opponent_tags_from_battles(
        battles,
        player_tag,
        arena_id=arena_id,
        max_tags=max_players,
    ):
        if tag not in seen:
            seen.add(tag)
            candidates.append(tag)

    # If arena filter on battles was too strict, retry without arena filter.
    if len(candidates) < 8:
        for tag in _opponent_tags_from_battles(battles, player_tag, arena_id=None, max_tags=max_players):
            if tag not in seen:
                seen.add(tag)
                candidates.append(tag)

    for tag in await _tags_from_player_clans(
        client,
        player_tag,
        trophy_low,
        trophy_high,
        max_tags=20,
    ):
        if tag not in seen:
            seen.add(tag)
            candidates.append(tag)

    for tag in await _tags_from_rankings(client, trophy_low, trophy_high, max_tags=80):
        if tag not in seen:
            seen.add(tag)
            candidates.append(tag)

    if not candidates:
        wide_low = max(0, trophy_low - 400)
        wide_high = trophy_high + 400
        for tag in await _tags_from_rankings(client, wide_low, wide_high, max_tags=100):
            if tag not in seen:
                seen.add(tag)
                candidates.append(tag)

    if arena_id is not None and candidates:
        return await _prefer_same_arena(
            client,
            candidates,
            arena_id,
            max_players=max_players,
            min_keep=6,
        )

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


def _merge_deck_stats(target: dict[str, dict], source: dict[str, dict]) -> None:
    for key, data in source.items():
        bucket = target[key]
        bucket["wins"] += data["wins"]
        bucket["total"] += data["total"]
        bucket["cards"] = data["cards"] or bucket["cards"]
        bucket["variants"].extend(data.get("variants") or [])
        bucket["players"] = int(bucket.get("players") or 0) + int(data.get("players") or 0)


def _stats_to_entries(deck_stats: dict[str, dict], *, id_base: int) -> list[dict]:
    ranked = []
    for data in deck_stats.values():
        cards = data.get("cards") or []
        if len(cards) != 8:
            continue
        total = int(data["total"])
        players = max(1, int(data.get("players") or 0))
        wr = round(data["wins"] / total * 100, 1) if total else 0.0
        ranked.append((total, wr, players, data))

    ranked.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    entries: list[dict] = []
    for i, (total, wr, players, data) in enumerate(ranked[:12]):
        cards = data["cards"]
        variant = data["variants"][0] if data.get("variants") else None
        card_infos, avg = _cards_to_infos(cards, variant)
        if total:
            desc = f"Арена · {players} игрок(ов) · {wr:.0f}% · {total} боёв"
        else:
            desc = f"Арена · {players} игрок(ов) · текущая колода"
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
        _arena_cache[cache_key] = _ArenaCacheEntry(
            data=data,
            updated_at=time.time(),
            version=_ARENA_CACHE_VERSION,
        )
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

    combined_stats: dict[str, dict] = defaultdict(_empty_stats_bucket)

    # Instant baseline from the user's own recent matchmaking sample.
    seeded = _seed_decks_from_battles(battles, player_tag, arena_id=arena_id)
    if not seeded and arena_id is not None:
        seeded = _seed_decks_from_battles(battles, player_tag, arena_id=None)
    _merge_deck_stats(combined_stats, seeded)

    client = ClashRoyaleClient()
    scanned = 0
    try:
        tags = await _discover_arena_player_tags(
            client,
            player_tag,
            trophies,
            arena_id,
            battles,
        )
        if tags:
            sem = asyncio.Semaphore(_SCAN_CONCURRENCY)

            async def guarded(tag: str) -> dict[str, dict]:
                async with sem:
                    return await _scan_player_tv_royale_deck(client, tag)

            results = await asyncio.gather(*[guarded(tag) for tag in tags], return_exceptions=True)
            for result in results:
                if isinstance(result, dict) and result:
                    _merge_deck_stats(combined_stats, result)
                    scanned += 1
    finally:
        await client.close()

    entries = _stats_to_entries(combined_stats, id_base=4000)
    entries.sort(
        key=lambda e: (
            -(e.get("total_games") or 0),
            -(e.get("winrate") or 0),
        ),
    )

    has_live = bool(entries)
    if scanned > 0 and has_live:
        source = "arena_live"
    elif seeded and has_live:
        source = "arena_battles"
    elif has_live:
        source = "arena_pool"
    else:
        source = "empty"
        logger.info(
            "Arena decks empty for tag=%s trophies=%s arena_id=%s battles=%s",
            player_tag,
            trophies,
            arena_id,
            len(battles or []),
        )

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
