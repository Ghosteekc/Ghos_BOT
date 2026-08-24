"""Meta decks API: league / trophy road sample + clan-war snapshot."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.deps import get_db, require_linked_player
from bot.api.schemas import MetaLadderResponse, MetaWarResponse
from bot.models.database import User
from bot.services.card_registry import ensure_cards_loaded
from bot.services.meta_query import get_clan_wars_meta, get_ladder_meta
from bot.services.meta_stats import MODE_LEAGUE, MODE_TROPHIES
from bot.services.pro.entitlement import is_user_pro

router = APIRouter(prefix="/api/meta", tags=["meta"])

FREE_META_DECK_LIMIT = 5


def _apply_pro_limit(payload: dict[str, Any], *, is_pro: bool) -> dict[str, Any]:
    """FREE plan sees the top 5 meta decks; the rest needs Ghosteek Pro."""
    decks = list(payload.get("decks") or [])
    total = len(decks)
    visible = decks if is_pro else decks[:FREE_META_DECK_LIMIT]
    return {
        **payload,
        "decks": visible,
        "is_pro": is_pro,
        "total_decks": total,
        "pro_locked_count": total - len(visible),
    }


@router.get("/league", response_model=MetaLadderResponse)
async def meta_league(
    user: User = Depends(require_linked_player),
    session: AsyncSession = Depends(get_db),
) -> MetaLadderResponse:
    await ensure_cards_loaded()
    is_pro = await is_user_pro(session, user)
    return MetaLadderResponse(**_apply_pro_limit(await get_ladder_meta(MODE_LEAGUE), is_pro=is_pro))


@router.get("/trophies", response_model=MetaLadderResponse)
async def meta_trophies(
    user: User = Depends(require_linked_player),
    session: AsyncSession = Depends(get_db),
) -> MetaLadderResponse:
    await ensure_cards_loaded()
    is_pro = await is_user_pro(session, user)
    return MetaLadderResponse(**_apply_pro_limit(await get_ladder_meta(MODE_TROPHIES), is_pro=is_pro))


@router.get("/clan-wars", response_model=MetaWarResponse)
async def meta_clan_wars(
    user: User = Depends(require_linked_player),
    session: AsyncSession = Depends(get_db),
) -> MetaWarResponse:
    await ensure_cards_loaded()
    is_pro = await is_user_pro(session, user)
    return MetaWarResponse(**_apply_pro_limit(await get_clan_wars_meta(), is_pro=is_pro))
