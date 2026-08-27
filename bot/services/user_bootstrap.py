"""Warm battles and related caches for a newly linked user."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from bot.models.database import User, async_session
from bot.services.battle_service import load_and_persist
from bot.services.battle_session_cache import set_session_battles
from bot.services.clash_api import ClashRoyaleClient, normalize_tag

logger = logging.getLogger(__name__)


def _as_user_ref(user: User | SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        id=int(user.id),
        telegram_id=int(user.telegram_id),
        player_tag=user.player_tag,
        player_name=getattr(user, "player_name", None),
        arena_id=getattr(user, "arena_id", None),
        trophies=getattr(user, "trophies", None),
    )


async def _profile_current_deck(player_tag: str) -> list[dict]:
    from bot.services.top_players import _cards_from_current_deck

    client = ClashRoyaleClient()
    try:
        player = await client.get_player(player_tag)
        return _cards_from_current_deck(player) or []
    except Exception:
        logger.debug("Bootstrap: currentDeck fetch failed for %s", player_tag, exc_info=True)
        return []
    finally:
        await client.close()


async def bootstrap_linked_user(user: User | SimpleNamespace, *, force: bool = True) -> dict[str, Any]:
    """Prefetch CR battlelog + mine-deck slots so Mini App opens with real data.

    Called after /link and from POST /api/sync.
    """
    ref = _as_user_ref(user)
    raw_tag = str(ref.player_tag or "").strip()
    if not raw_tag:
        return {"ok": False, "battles_loaded": 0, "mine_decks": 0}
    tag = normalize_tag(raw_tag)
    if not tag or tag == "#":
        return {"ok": False, "battles_loaded": 0, "mine_decks": 0}

    battles = await load_and_persist(ref, force_refresh=force)  # type: ignore[arg-type]
    battles = list(battles or [])
    if battles:
        set_session_battles(ref.telegram_id, tag, battles)

    mine_decks = 0
    try:
        from bot.services.mine_decks import sync_tracked_mine_decks

        profile_deck = await _profile_current_deck(tag)
        rows = await sync_tracked_mine_decks(
            ref,  # type: ignore[arg-type]
            live_battles=battles,
            profile_deck=profile_deck or None,
        )
        mine_decks = len(rows)
    except Exception:
        logger.exception("Bootstrap: mine decks sync failed for %s", tag)

    logger.info(
        "Bootstrap ready telegram_id=%s tag=%s battles=%s mine_decks=%s",
        ref.telegram_id,
        tag,
        len(battles),
        mine_decks,
    )
    return {
        "ok": True,
        "battles_loaded": len(battles),
        "mine_decks": mine_decks,
    }


async def bootstrap_user_by_telegram_id(telegram_id: int) -> dict[str, Any]:
    """Load user from DB and warm caches (safe for background tasks after /link)."""
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = res.scalar_one_or_none()
        if user is None or not user.player_tag:
            return {"ok": False, "battles_loaded": 0, "mine_decks": 0}
        ref = _as_user_ref(user)

    return await bootstrap_linked_user(ref, force=True)
