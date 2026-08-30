"""Фоновый прогрев кешей сразу после старта API.

Раньше top-players/meta подтягивались только из sync-цикла
(после sync_startup_delay_sec) или по первому запросу webapp —
из-за этого UI «догонял» данные уже после входа.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


async def warmup_caches() -> None:
    """Карты каталога + топ игроки + meta — параллельно, не блокируя polling."""
    started = time.monotonic()
    logger.info("Startup warmup: loading cards, top players, meta...")

    try:
        from bot.services.card_registry import ensure_cards_loaded

        await ensure_cards_loaded()
    except Exception:
        logger.exception("Startup warmup: card catalog failed")

    results = await asyncio.gather(
        _warmup_top_players(),
        _warmup_meta(),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Startup warmup task error: %s", result)

    logger.info("Startup warmup finished in %.1fs", time.monotonic() - started)


async def _warmup_top_players() -> None:
    from bot.services.top_players import get_top_players

    cache = await get_top_players(limit=100, force=False)
    logger.info(
        "Startup warmup: top players ready (%d decks)",
        len(cache.players),
    )


async def _warmup_meta() -> None:
    logger.info("Startup warmup: meta collector runs on its own schedule")
