"""Sync user battle logs into BattleCache."""

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select

from bot.config import settings
from bot.models.database import async_session, User
from bot.services.battle_service import filter_pvp_battles, persist_battles
from bot.services.battle_session_cache import is_fresh
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag

logger = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()
_cycle_counter = 0


async def _fetch_battlelog(client: ClashRoyaleClient, player_tag: str) -> list:
    timeout = max(15, settings.sync_cr_api_timeout_sec)
    try:
        return await asyncio.wait_for(client.get_battlelog(player_tag), timeout=timeout)
    except asyncio.TimeoutError as exc:
        logger.warning(
            "CR API timeout (%ss) fetching battlelog for %s",
            timeout,
            player_tag,
        )
        raise ClashRoyaleAPIError(
            f"Battlelog request timed out after {timeout}s",
            0,
            retryable=False,
        ) from exc


async def sync_user_battles(user: User, *, client: ClashRoyaleClient | None = None) -> int:
    """Fetch user's battlelog and persist new PvP battles. Returns number of new saved battles."""
    if not user.player_tag:
        return 0

    tag = normalize_tag(user.player_tag)
    if is_fresh(tag):
        logger.debug("Battle sync skipped for %s: battlelog fetched recently", tag)
        return 0

    owns_client = client is None
    client = client or ClashRoyaleClient()
    try:
        battles = await _fetch_battlelog(client, user.player_tag)
    except ClashRoyaleAPIError as exc:
        logger.warning("Failed to fetch battles for %s: %s", user.player_tag, exc)
        return 0
    except Exception:
        logger.exception("Unexpected error fetching battles for %s", user.player_tag)
        return 0
    finally:
        if owns_client:
            await client.close()

    pvp = filter_pvp_battles(battles, user.player_tag)
    return await persist_battles(user, pvp)


async def sync_all_once(*, stop_event: asyncio.Event | None = None) -> dict[str, int]:
    """Sync all users once. Returns dict of player_tag -> new_count."""
    async with _sync_lock:
        return await _sync_all_once_locked(stop_event=stop_event)


async def _sync_all_once_locked(*, stop_event: asyncio.Event | None = None) -> dict[str, int]:
    results: dict[str, int] = {}
    async with async_session() as session:
        res = await session.execute(select(User).where(User.player_tag != None))
        users = res.scalars().all()

    if not users:
        logger.info("Battle sync: no linked users")
        return results

    client = ClashRoyaleClient()
    try:
        for user in users:
            if stop_event and stop_event.is_set():
                logger.info("Battle sync interrupted: shutdown requested")
                break
            tag = normalize_tag(user.player_tag)
            try:
                new = await sync_user_battles(user, client=client)
                if new:
                    logger.info("Synced %s: %d new battles", user.player_tag, new)
                results[tag] = new
            except Exception:
                logger.exception("Error syncing %s", user.player_tag)
                results[tag] = 0
            await asyncio.sleep(1)
    finally:
        await client.close()

    return results


async def _refresh_meta_safe() -> None:
    try:
        from bot.services.meta_analyzer import refresh_meta_background

        await refresh_meta_background()
    except ClashRoyaleAPIError as exc:
        if exc.status == 429:
            logger.warning("Background meta refresh skipped after rate limit: %s", exc)
            return
        logger.exception("Background meta refresh failed")
    except Exception:
        logger.exception("Background meta refresh failed")


async def _run_sync_cycle(cycle_id: int, stop_event: asyncio.Event) -> dict[str, Any]:
    started = time.monotonic()
    logger.info("Battle sync cycle #%d started", cycle_id)

    battle_results: dict[str, int] = {}
    battle_error: str | None = None
    try:
        battle_results = await sync_all_once(stop_event=stop_event)
    except asyncio.CancelledError:
        raise
    except Exception:
        battle_error = "failed"
        logger.exception("Battle sync cycle #%d failed during user sync", cycle_id)

    meta_error = False
    if not stop_event.is_set():
        try:
            await _refresh_meta_safe()
        except asyncio.CancelledError:
            raise
        except Exception:
            meta_error = True

    elapsed = time.monotonic() - started
    users = len(battle_results)
    new_total = sum(battle_results.values())
    logger.info(
        "Battle sync cycle #%d finished in %.1fs (users=%d, new_battles=%d, battle=%s, meta_error=%s)",
        cycle_id,
        elapsed,
        users,
        new_total,
        battle_error or "ok",
        meta_error,
    )
    return {
        "cycle": cycle_id,
        "elapsed_sec": round(elapsed, 2),
        "users": users,
        "new_battles": new_total,
        "battle_error": battle_error,
        "meta_error": meta_error,
    }


async def run_periodic(stop_event: asyncio.Event) -> None:
    global _cycle_counter
    interval = max(1, settings.sync_interval_minutes) * 60
    logger.info("Battle sync loop started (interval %d seconds)", interval)

    startup_delay = max(0, settings.sync_startup_delay_sec)
    if startup_delay and not stop_event.is_set():
        logger.info("Battle sync: waiting %ds after startup before first cycle", startup_delay)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=startup_delay)
        except asyncio.TimeoutError:
            pass

    try:
        while not stop_event.is_set():
            _cycle_counter += 1
            try:
                await _run_sync_cycle(_cycle_counter, stop_event)
            except asyncio.CancelledError:
                logger.info("Battle sync cycle cancelled during shutdown")
                raise

            if stop_event.is_set():
                break

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        logger.info("Battle sync loop cancelled")
        raise
    finally:
        logger.info("Battle sync loop stopped")


def is_sync_running() -> bool:
    return _sync_lock.locked()
