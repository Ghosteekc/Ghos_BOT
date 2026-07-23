from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.deps import get_current_user, get_db
from bot.api.schemas import (
    CardCatalogResponse,
    FavoriteDeckEntry,
    FavoritesResponse,
    SearchResult,
    SettingsResponse,
    SettingsUpdateRequest,
    SyncResponse,
)
from bot.models.database import BattleCache, FavoriteDeck, User, async_session
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded, get_cards_catalog
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag, validate_tag
from bot.services.battle_service import load_and_persist
from bot.services.user_settings import load_settings_response, update_user_settings
from bot.user_errors import http_error, http_error_from_clash

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/cards/catalog", response_model=CardCatalogResponse)
async def cards_catalog(user: User = Depends(get_current_user)) -> CardCatalogResponse:
    del user
    items = await get_cards_catalog()
    return CardCatalogResponse(cards=items)


class FavoriteDeckPayload(BaseModel):
    deck: list[str]


@router.get("/search", response_model=list[SearchResult])
async def search_player(
    q: str = Query(..., min_length=3),
    user: User = Depends(get_current_user),
) -> list[SearchResult]:
    del user
    tag = normalize_tag(q.strip())
    if not validate_tag(tag):
        raise http_error(
            "E001",
            status=400,
            message="Поиск только по тегу игрока, например #ABC123",
        )

    client = ClashRoyaleClient()
    try:
        player = await client.get_player(tag)
    except ClashRoyaleAPIError as e:
        raise http_error_from_clash(e) from e
    finally:
        await client.close()

    arena = player.get("arena", {})
    clan = player.get("clan") or {}
    return [
        SearchResult(
            player_tag=tag.replace("#", ""),
            player_name=player.get("name", "Игрок"),
            trophies=player.get("trophies", 0),
            arena=arena.get("name", "—"),
            max_trophies=player.get("bestTrophies"),
            clan_name=clan.get("name") if isinstance(clan, dict) else None,
            exp_level=player.get("expLevel"),
        )
    ]


@router.get("/players/{tag}", response_model=SearchResult)
async def get_player_preview(
    tag: str,
    user: User = Depends(get_current_user),
) -> SearchResult:
    del user
    normalized = normalize_tag(tag.strip())
    if not validate_tag(normalized):
        raise http_error("E001", status=400, message="Некорректный тег игрока")

    client = ClashRoyaleClient()
    try:
        player = await client.get_player(normalized)
    except ClashRoyaleAPIError as e:
        raise http_error_from_clash(e) from e
    finally:
        await client.close()

    arena = player.get("arena", {})
    clan = player.get("clan") or {}
    return SearchResult(
        player_tag=normalized.replace("#", ""),
        player_name=player.get("name", "Игрок"),
        trophies=player.get("trophies", 0),
        arena=arena.get("name", "—"),
        max_trophies=player.get("bestTrophies"),
        clan_name=clan.get("name") if isinstance(clan, dict) else None,
        exp_level=player.get("expLevel"),
    )


@router.get("/favorites", response_model=FavoritesResponse)
async def get_favorites(user: User = Depends(get_current_user)) -> FavoritesResponse:
    await ensure_cards_loaded()
    async with async_session() as session:
        res = await session.execute(
            select(FavoriteDeck).where(FavoriteDeck.user_id == user.id).order_by(FavoriteDeck.created_at.desc())
        )
        rows = res.scalars().all()

    decks: list[list[str]] = []
    entries: list[FavoriteDeckEntry] = []
    for row in rows:
        cards = [c for c in row.deck_key.split(",") if c]
        decks.append(cards)
        entries.append(FavoriteDeckEntry(
            cards=cards,
            deck_link=build_deck_share_link(cards) if len(cards) == 8 else None,
        ))
    return FavoritesResponse(decks=decks, entries=entries)


@router.post("/favorites")
async def add_favorite_deck(
    payload: FavoriteDeckPayload,
    user: User = Depends(get_current_user),
) -> dict:
    cards = [c.strip() for c in payload.deck if c.strip()]
    if len(cards) != 8:
        raise HTTPException(status_code=400, detail="Колода должна содержать 8 карт")

    deck_key = ",".join(cards)
    async with async_session() as session:
        res = await session.execute(
            select(FavoriteDeck).where(
                FavoriteDeck.user_id == user.id,
                FavoriteDeck.deck_key == deck_key,
            )
        )
        if res.scalar_one_or_none() is None:
            session.add(FavoriteDeck(user_id=user.id, deck_key=deck_key))
            await session.commit()
    return {"ok": True}


@router.delete("/favorites")
async def remove_favorite_deck(
    payload: FavoriteDeckPayload,
    user: User = Depends(get_current_user),
) -> dict:
    deck_key = ",".join(c.strip() for c in payload.deck if c.strip())
    async with async_session() as session:
        res = await session.execute(
            select(FavoriteDeck).where(
                FavoriteDeck.user_id == user.id,
                FavoriteDeck.deck_key == deck_key,
            )
        )
        row = res.scalar_one_or_none()
        if row:
            await session.delete(row)
            await session.commit()
    return {"ok": True}


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    return await load_settings_response(session, user.id)


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    return await update_user_settings(session, user.id, payload)


@router.post("/cache/clear")
async def clear_cache(user: User = Depends(get_current_user)) -> dict:
    from bot.services.battle_session_cache import clear_user
    from bot.services.clash_api import normalize_tag

    tag = normalize_tag(user.player_tag) if user.player_tag else None
    clear_user(user.telegram_id, tag)

    if user.player_tag:
        async with async_session() as session:
            await session.execute(delete(BattleCache).where(BattleCache.player_tag == tag))
            await session.commit()

    return {"ok": True}


@router.post("/sync", response_model=SyncResponse)
async def sync_player_data(user: User = Depends(get_current_user)) -> SyncResponse:
    if not user.player_tag:
        raise HTTPException(status_code=400, detail="Сначала привяжите аккаунт в боте: /link #ТЕГ")

    from bot.services.battle_session_cache import clear_user, set_session_battles
    from bot.services.clash_api import normalize_tag

    tag = normalize_tag(user.player_tag)
    clear_user(user.telegram_id, tag)

    battles = await load_and_persist(user, force_refresh=True)
    if battles:
        set_session_battles(user.telegram_id, tag, battles)

    return SyncResponse(ok=True, battles_loaded=len(battles or []))
