"""Single in-flight Clash Royale battlelog fetch per player tag."""

from __future__ import annotations

import asyncio
import logging

from bot.services.battle_session_cache import mark_tag_fetched
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_inflight: dict[str, asyncio.Task[list]] = {}


async def coalesced_battlelog(client: ClashRoyaleClient, player_tag: str) -> list:
    """Share one CR battlelog request when sync, webapp and profile call at once."""
    tag = normalize_tag(player_tag)

    async with _lock:
        task = _inflight.get(tag)
        if task is not None and not task.done():
            logger.debug("Battlelog coalesce: waiting on in-flight fetch for %s", tag)
        elif task is not None and task.done():
            _inflight.pop(tag, None)
            task = None

        if task is None:
            task = asyncio.create_task(_fetch_uncached(client, player_tag))
            _inflight[tag] = task

    try:
        return await asyncio.shield(task)
    except ClashRoyaleAPIError:
        async with _lock:
            if _inflight.get(tag) is task:
                _inflight.pop(tag, None)
        raise


async def _fetch_uncached(client: ClashRoyaleClient, player_tag: str) -> list:
    data = await client.fetch_battlelog_raw(player_tag)
    mark_tag_fetched(normalize_tag(player_tag))
    return data
