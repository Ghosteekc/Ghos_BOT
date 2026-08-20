"""Persistent CR API collector for league and trophy-road meta decks."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.database import (
    MetaBattleObservation,
    MetaDeckAggregate,
    MetaDeckDailyStat,
    MetaSnapshot,
    User,
    async_session,
)
from bot.services.card_registry import ensure_cards_loaded
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient
from bot.services.clan_war_decks import refresh_clan_war_snapshot
from bot.services.meta_battle_cache_ingest import ingest_trophies_from_battle_cache
from bot.services.meta_observation import observation_from_battle
from bot.services.meta_stats import (
    MODE_LEAGUE,
    MODE_TROPHIES,
    parse_battle_datetime,
    ranking_score,
    utc_day,
)

logger = logging.getLogger(__name__)

_LEAGUE_RANK_PATHS = (
    "/locations/global/pathoflegend/players?limit={limit}",
    "/locations/57000249/pathoflegend/players?limit={limit}",
)
_TROPHY_RANK_PATHS = (
    "/locations/global/rankings/players?limit={limit}",
    "/locations/57000006/rankings/players?limit={limit}",
)

_collect_lock = asyncio.Lock()


async def _fetch_ranking(client: ClashRoyaleClient, paths: tuple[str, ...], limit: int) -> list[dict]:
    for template in paths:
        path = template.format(limit=limit)
        try:
            data = await client._request(path)
            items = data.get("items", []) if isinstance(data, dict) else []
            if items:
                logger.info("Meta collector ranking %s (%d players)", path, len(items))
                return items[:limit]
        except ClashRoyaleAPIError as exc:
            if exc.status == 429:
                raise
            logger.debug("Meta ranking unavailable at %s: %s", path, exc)
    return []


def _seed_players() -> list[dict]:
    from bot.config import settings

    out: list[dict] = []
    for raw_tag in settings.meta_seed_tags.split(","):
        tag = raw_tag.strip()
        if not tag:
            continue
        out.append({"tag": tag if tag.startswith("#") else f"#{tag}", "name": tag})
    return out


def _merge_players(*groups: list[dict]) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for group in groups:
        for item in group:
            tag = str(item.get("tag") or "").upper()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            merged.append(item)
    return merged


async def _linked_player_tags(limit: int = 100) -> list[dict]:
    async with async_session() as session:
        tags = (
            await session.execute(
                select(User.player_tag)
                .where(User.player_tag.is_not(None))
                .limit(max(1, limit))
            )
        ).scalars().all()
    out: list[dict] = []
    for tag in tags:
        clean = str(tag or "").strip()
        if not clean:
            continue
        normalized = clean if clean.startswith("#") else f"#{clean}"
        out.append({"tag": normalized, "name": normalized})
    return out


async def _players_for_mode(client: ClashRoyaleClient, mode: str) -> list[dict]:
    base_limit = max(8, settings.meta_collector_players)
    if mode == MODE_TROPHIES:
        from bot.services.arena_decks import _tags_from_player_clans, _tags_from_rankings

        trophy_min = max(0, settings.meta_trophy_min)
        trophy_high = trophy_min + 3000
        band_tags = await _tags_from_rankings(
            client,
            max(0, trophy_min - 500),
            trophy_high,
            max_tags=max(80, base_limit * 3),
        )
        players = [{"tag": tag, "name": tag} for tag in band_tags]
        players = _merge_players(players, _seed_players(), await _linked_player_tags())

        for item in players[:12]:
            tag = item.get("tag") or ""
            if not tag:
                continue
            clan_tags = await _tags_from_player_clans(
                client,
                tag,
                max(0, trophy_min - 1000),
                trophy_high + 1000,
                max_tags=20,
            )
            for clan_tag in clan_tags:
                players = _merge_players(players, [{"tag": clan_tag, "name": clan_tag}])
        return players[: max(120, base_limit * 3)]

    paths = _LEAGUE_RANK_PATHS
    players = await _fetch_ranking(client, paths, base_limit)
    return _merge_players(players, await _linked_player_tags(limit=40))

async def _insert_observations_safe(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Insert ignoring duplicates. Uses per-row SAVEPOINT so one clash does not abort the batch."""
    inserted = 0
    for row in rows:
        try:
            async with session.begin_nested():
                session.add(MetaBattleObservation(**row))
                await session.flush()
            inserted += 1
        except IntegrityError:
            continue
    return inserted


async def rebuild_mode_aggregates(session: AsyncSession, mode: str) -> int:
    obs_rows = (
        await session.execute(
            select(MetaBattleObservation).where(MetaBattleObservation.mode == mode)
        )
    ).scalars().all()

    buckets: dict[str, dict[str, Any]] = {}
    daily: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"games": 0, "wins": 0, "losses": 0, "players": set()}
    )
    max_games = 1
    for obs in obs_rows:
        bucket = buckets.setdefault(
            obs.deck_hash,
            {
                "games": 0,
                "wins": 0,
                "losses": 0,
                "players": set(),
                "first": None,
                "last": None,
                "cards_csv": obs.cards_csv,
                "cards_json": obs.cards_json,
            },
        )
        bucket["games"] += 1
        if obs.result == "win":
            bucket["wins"] += 1
        elif obs.result == "loss":
            bucket["losses"] += 1
        bucket["players"].add(obs.player_tag)
        seen = parse_battle_datetime(obs.battle_time)
        if seen is not None:
            if bucket["first"] is None or seen < bucket["first"]:
                bucket["first"] = seen
            if bucket["last"] is None or seen > bucket["last"]:
                bucket["last"] = seen
                bucket["cards_csv"] = obs.cards_csv
                bucket["cards_json"] = obs.cards_json
        day = utc_day(obs.battle_time)
        if day:
            dkey = (obs.deck_hash, day)
            daily[dkey]["games"] += 1
            if obs.result == "win":
                daily[dkey]["wins"] += 1
            elif obs.result == "loss":
                daily[dkey]["losses"] += 1
            daily[dkey]["players"].add(obs.player_tag)
        max_games = max(max_games, bucket["games"])

    await session.execute(delete(MetaDeckAggregate).where(MetaDeckAggregate.mode == mode))
    # Daily rows are historical — never delete days that already exist.
    existing_daily = {
        (row.deck_hash, row.day): row
        for row in (
            await session.execute(
                select(MetaDeckDailyStat).where(MetaDeckDailyStat.mode == mode)
            )
        ).scalars().all()
    }

    now = datetime.now(timezone.utc)
    for deck_hash, data in buckets.items():
        games = int(data["games"])
        wins = int(data["wins"])
        losses = int(data["losses"])
        players = len(data["players"])
        session.add(
            MetaDeckAggregate(
                deck_hash=deck_hash,
                mode=mode,
                cards_csv=data["cards_csv"],
                cards_json=data["cards_json"],
                total_games=games,
                wins=wins,
                losses=losses,
                unique_players=players,
                ranking_score=ranking_score(
                    wins=wins,
                    games=games,
                    unique_players=players,
                    last_seen=data["last"],
                    max_games=max_games,
                    now=now,
                ),
                first_seen=data["first"],
                last_seen=data["last"],
                updated_at=now,
            )
        )

    for (deck_hash, day), data in daily.items():
        games = int(data["games"])
        wins = int(data["wins"])
        losses = int(data["losses"])
        players = len(data["players"])
        row = existing_daily.get((deck_hash, day))
        if row is not None:
            row.games = games
            row.wins = wins
            row.losses = losses
            row.unique_players = players
        else:
            session.add(
                MetaDeckDailyStat(
                    deck_hash=deck_hash,
                    mode=mode,
                    day=day,
                    games=games,
                    wins=wins,
                    losses=losses,
                    unique_players=players,
                )
            )
    return len(buckets)


async def _save_snapshot(session: AsyncSession, mode: str, source: str) -> None:
    rows = (
        await session.execute(
            select(MetaDeckAggregate)
            .where(MetaDeckAggregate.mode == mode)
            .order_by(MetaDeckAggregate.ranking_score.desc())
            .limit(settings.meta_ranking_limit)
        )
    ).scalars().all()
    payload = {
        "mode": mode,
        "count": len(rows),
        "hashes": [r.deck_hash for r in rows],
        "games": sum(r.total_games for r in rows),
    }
    session.add(
        MetaSnapshot(
            mode=mode,
            source=source,
            season=datetime.now(timezone.utc).strftime("%Y-%m"),
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
    )


async def collect_mode(mode: str) -> dict[str, Any]:
    """Fetch ranking + battlelogs for one mode and persist new observations."""
    await ensure_cards_loaded()
    trophy_min = max(0, settings.meta_trophy_min)
    concurrency = max(1, settings.meta_collector_concurrency)
    client = ClashRoyaleClient()
    source = "cr_api"
    new_obs = 0
    scanned = 0
    players: list[dict] = []
    try:
        players = await _players_for_mode(client, mode)
        source = f"cr_api:{mode}:{len(players)}"
        sem = asyncio.Semaphore(concurrency)
        observations: list[dict[str, Any]] = []

        async def fetch_one(item: dict) -> list[dict[str, Any]]:
            tag = item.get("tag") or ""
            if not tag:
                return []
            async with sem:
                try:
                    battles = await client.get_battlelog(tag)
                except ClashRoyaleAPIError as exc:
                    if exc.status == 429:
                        raise
                    logger.debug("Meta battlelog skip %s: %s", tag, exc)
                    return []
            out: list[dict[str, Any]] = []
            for battle in battles:
                row = observation_from_battle(tag, battle, trophy_min=trophy_min)
                if row and row["mode"] == mode:
                    out.append(row)
            return out

        results = await asyncio.gather(*[fetch_one(p) for p in players], return_exceptions=True)
        rate_limited = False
        for result in results:
            if isinstance(result, ClashRoyaleAPIError) and result.status == 429:
                rate_limited = True
                logger.warning("Meta collector hit 429 for mode=%s", mode)
                continue
            if isinstance(result, Exception):
                logger.debug("Meta collector player error: %s", result)
                continue
            scanned += 1
            observations.extend(result)
        if rate_limited and not observations:
            source = f"{source}:429"
    except ClashRoyaleAPIError as exc:
        if exc.status == 429:
            logger.warning("Meta collector ranking 429 mode=%s", mode)
            source = "cr_api:429"
        else:
            logger.warning("Meta collector failed mode=%s: %s", mode, exc)
            source = f"cr_api:error:{exc.status}"
    finally:
        await client.close()

    async with async_session() as session:
        if mode == MODE_TROPHIES:
            observations.extend(await ingest_trophies_from_battle_cache(session))
        if observations:
            new_obs = await _insert_observations_safe(session, observations)
        decks = await rebuild_mode_aggregates(session, mode)
        await _save_snapshot(session, mode, source)
        await session.commit()

    logger.info(
        "Meta collector mode=%s scanned=%d new_obs=%d decks=%d source=%s",
        mode,
        scanned,
        new_obs,
        decks,
        source,
    )
    return {"mode": mode, "scanned": scanned, "new_obs": new_obs, "decks": decks, "source": source}


async def _cw_player_pool(client: ClashRoyaleClient) -> list[dict[str, Any]]:
    from bot.services.arena_decks import _tags_from_player_clans

    linked = await _linked_player_tags(limit=120)
    league_players = await _players_for_mode(client, MODE_LEAGUE)
    trophy_players = await _players_for_mode(client, MODE_TROPHIES)
    players = _merge_players(linked, league_players, trophy_players)

    expanded: list[dict] = []
    for item in linked[:25]:
        tag = item.get("tag") or ""
        if not tag:
            continue
        for clan_tag in await _tags_from_player_clans(client, tag, 0, 30_000, max_tags=35):
            expanded.append({"tag": clan_tag, "name": clan_tag})
    return _merge_players(players, expanded)


async def collect_all() -> dict[str, Any]:
    async with _collect_lock:
        league = await collect_mode(MODE_LEAGUE)
        trophies = await collect_mode(MODE_TROPHIES)
        client = ClashRoyaleClient()
        try:
            cw_players = await _cw_player_pool(client)
            cw = await refresh_clan_war_snapshot(
                client,
                cw_players,
                concurrency=max(1, settings.meta_collector_concurrency),
                min_games=1,
            )
        finally:
            await client.close()
        return {
            "league": league,
            "trophies": trophies,
            "clan_wars": {"decks": len(cw.get("decks") or []), "available": cw.get("available")},
        }


async def run_periodic(stop_event: asyncio.Event) -> None:
    interval = max(15, settings.meta_collector_interval_minutes) * 60
    startup = max(0, settings.meta_collector_startup_delay_sec)
    logger.info(
        "Meta collector loop started (interval %ds, startup delay %ds)",
        interval,
        startup,
    )
    if startup and not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=startup)
            return
        except asyncio.TimeoutError:
            pass

    while not stop_event.is_set():
        started = time.monotonic()
        try:
            await collect_all()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Meta collector cycle failed")
        logger.info("Meta collector cycle finished in %.1fs", time.monotonic() - started)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
    logger.info("Meta collector loop stopped")
