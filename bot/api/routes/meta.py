"""Meta decks API: league / trophy road sample + clan-war snapshot."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from bot.api.deps import require_linked_player
from bot.api.schemas import MetaLadderResponse, MetaWarResponse
from bot.models.database import User
from bot.services.card_registry import ensure_cards_loaded
from bot.services.meta_query import get_clan_wars_meta, get_ladder_meta
from bot.services.meta_stats import MODE_LEAGUE, MODE_TROPHIES

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/league", response_model=MetaLadderResponse)
async def meta_league(_user: User = Depends(require_linked_player)) -> MetaLadderResponse:
    await ensure_cards_loaded()
    return MetaLadderResponse(**await get_ladder_meta(MODE_LEAGUE))


@router.get("/trophies", response_model=MetaLadderResponse)
async def meta_trophies(_user: User = Depends(require_linked_player)) -> MetaLadderResponse:
    await ensure_cards_loaded()
    return MetaLadderResponse(**await get_ladder_meta(MODE_TROPHIES))


@router.get("/clan-wars", response_model=MetaWarResponse)
async def meta_clan_wars(_user: User = Depends(require_linked_player)) -> MetaWarResponse:
    await ensure_cards_loaded()
    return MetaWarResponse(**await get_clan_wars_meta())
