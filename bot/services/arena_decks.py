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
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag
from bot.services.deck_analyzer import extract_deck
from bot.services.meta_analyzer import _guess_deck_name, _guess_category, _is_competitive_battle

logger = logging.getLogger(__name__)

_SCAN_CONCURRENCY = 5
_arena_refresh_lock = asyncio.Lock()


@dataclass
class _ArenaCacheEntry:
    data: dict
    updated_at: float
    version: int = 1

    def expired(self) -> bool:
        ttl = max(300, settings.meta_refresh_hours * 3600)
        return (time.time() - self.updated_at) > ttl


_arena_cache: dict[str, _ArenaCacheEntry] = {}


def _arena_cache_key(player_tag: str, trophies: int, arena_id: int | None) -> str:
    bucket = max(0, trophies // 250) * 250
    arena_part = str(arena_id) if arena_id is not None else "na"
    return f"{normalize_tag(player_tag)}:{arena_part}:{bucket}"


def _trophy_window(trophies: int) -> int:
    if trophies >= 9000:
        return 500
    if trophies >= 7000:
        return 400
    if trophies >= 5000:
        return 350
    return 300


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


def _decks_from_user_battles(
    battles: list,
    player_tag: str,
    trophies: int,
) -> dict[str, dict]:
    """Opponent decks from user's battles at similar trophy range."""
    tag_norm = normalize_tag(player_tag)
    window = _trophy_window(trophies)
    deck_stats: dict[str, dict] = defaultdict(
        lambda: {"wins": 0, "total": 0, "cards": [], "variants": []},
    )

    for battle in battles:
        btype = (battle.get("type") or "").lower()
        if btype in ("friendly", "clanmate", "warday", "boatbattle", "challenge"):
            continue
        team = battle.get("team", [{}])[0]
        if team.get("tag") and normalize_tag(team.get("tag", "")) != tag_norm:
            continue
        opponent = battle.get("opponent", [{}])[0]
        opp_trophies = int(opponent.get("startingTrophies") or 0)
        if trophies > 0 and opp_trophies > 0 and abs(opp_trophies - trophies) > window:
            continue
        cards = extract_deck(opponent)
        if len(cards) != 8:
            continue
        key = "|".join(sorted(cards))
        bucket = deck_stats[key]
        bucket["total"] += 1
        bucket["cards"] = cards
        parsed = cards_from_team(opponent)
        if len(parsed) == 8:
            bucket["variants"].append(parsed)
        if team.get("crowns", 0) > opponent.get("crowns", 0):
            bucket["wins"] += 1

    return deck_stats


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

    results = await asyncio.gather(*[check(tag) for tag in tags[:80]], return_exceptions=True)
    for result in results:
        if isinstance(result, str) and result not in matched:
            matched.append(result)
        if len(matched) >= max_players:
            break
    return matched


async def _fetch_bracket_player_tags(
    client: ClashRoyaleClient,
    trophies: int,
    battles: list,
    player_tag: str,
    arena_id: int | None,
    *,
    max_players: int = 25,
) -> list[str]:
    """Top players near the user's trophies; prefer the same arena id."""
    window = _trophy_window(trophies)
    candidates: list[str] = []
    seen: set[str] = set()

    ranking_paths = ["/locations/global/rankings/players?limit=200"]
    if trophies >= 9000:
        ranking_paths.insert(0, "/locations/global/pathoflegend/rankings/players?limit=200")

    for path in ranking_paths:
        try:
            data = await client._request(path)
            items = data.get("items", []) if isinstance(data, dict) else []
            bracket = [
                item for item in items
                if abs(int(item.get("trophies") or 0) - trophies) <= window
            ]
            bracket.sort(key=lambda x: abs(int(x.get("trophies") or 0) - trophies))
            for item in bracket:
                tag = (item.get("tag") or "").upper()
                if tag and tag not in seen:
                    seen.add(tag)
                    candidates.append(tag)
        except ClashRoyaleAPIError as e:
            logger.debug("Rankings fetch for arena decks %s: %s", path, e)

    tag_norm = normalize_tag(player_tag)
    for battle in battles[:40]:
        opponent = battle.get("opponent", [{}])[0]
        tag = (opponent.get("tag") or "").upper()
        if not tag or tag in seen or tag == tag_norm:
            continue
        opp_trophies = int(opponent.get("startingTrophies") or 0)
        if trophies > 0 and opp_trophies > 0 and abs(opp_trophies - trophies) > window:
            continue
        seen.add(tag)
        candidates.append(tag)

    if arena_id is not None:
        arena_tags = await _filter_tags_by_arena(client, candidates, arena_id, max_players=max_players)
        if len(arena_tags) >= 3:
            return arena_tags
        if arena_tags:
            return arena_tags

    return candidates[:max_players]


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


def _stats_to_entries(deck_stats: dict[str, dict], *, id_base: int, min_games: int) -> list[dict]:
    ranked = []
    for data in deck_stats.values():
        if data["total"] < min_games:
            continue
        wr = round(data["wins"] / data["total"] * 100, 1)
        ranked.append((wr, data["total"], data))

    ranked.sort(key=lambda x: (-x[0], -x[1]))
    entries: list[dict] = []
    for i, (wr, total, data) in enumerate(ranked[:12]):
        cards = data["cards"]
        variant = data["variants"][0] if data.get("variants") else None
        card_infos, avg = _cards_to_infos(cards, variant)
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
            "description": f"Винрейт {wr:.0f}% · {total} боёв на вашей арене",
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
        lambda: {"wins": 0, "total": 0, "cards": [], "variants": []},
    )
    _merge_deck_stats(combined_stats, _decks_from_user_battles(battles, player_tag, trophies))

    client = ClashRoyaleClient()
    scanned = 0
    try:
        tags = await _fetch_bracket_player_tags(
            client,
            trophies,
            battles,
            player_tag,
            arena_id,
        )
        sem = asyncio.Semaphore(_SCAN_CONCURRENCY)

        async def guarded(tag: str) -> dict[str, dict]:
            async with sem:
                return await _scan_player_deck_stats(client, tag)

        results = await asyncio.gather(*[guarded(tag) for tag in tags], return_exceptions=True)
        for result in results:
            if isinstance(result, dict):
                _merge_deck_stats(combined_stats, result)
                scanned += 1
    finally:
        await client.close()

    entries = _stats_to_entries(combined_stats, id_base=4000, min_games=3)
    entries = [e for e in entries if e.get("total_games", 0) > 0]
    entries.sort(key=lambda e: (-e.get("winrate", 0), -e.get("total_games", 0)))

    has_live = bool(entries)
    if scanned > 0 and has_live:
        source = "arena_rankings"
    elif has_live:
        source = "battles"
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
