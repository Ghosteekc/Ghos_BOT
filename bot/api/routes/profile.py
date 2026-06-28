import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.deps import get_current_user, get_db, get_subscription_info
from bot.api.schemas import ProfileResponse, SubscriptionInfo
from bot.models.database import User
from bot.services.battle_service import get_cached_stats
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["profile"])


@router.get("/me", response_model=ProfileResponse)
async def get_profile(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    sub_info = await get_subscription_info(user, session)

    if not user.player_tag:
        return ProfileResponse(
            player_tag=None,
            player_name=user.player_name,
            trophies=None,
            exp_level=None,
            arena_name=None,
            subscription=SubscriptionInfo(**sub_info),
        )

    client = ClashRoyaleClient()
    try:
        player = await client.get_player(user.player_tag)
    except ClashRoyaleAPIError as e:
        logger.warning(f"Failed to fetch live profile for {user.player_tag}: {e}")
        player = None
    finally:
        await client.close()

    if player:
        arena = player.get("arena", {})
        return ProfileResponse(
            player_tag=user.player_tag,
            player_name=player.get("name"),
            trophies=player.get("trophies", 0),
            exp_level=player.get("expLevel"),
            arena_name=arena.get("name"),
            subscription=SubscriptionInfo(**sub_info),
        )

    arena_name = None
    if user.arena_id:
        arena_names = {
            0: "Тренировочный лагерь", 1: "Гоблинская арена", 2: "Арена песков",
            3: "Драконья арена", 4: "Нижняя пик", 5: "Арена рабочих",
            6: "Сахарная фотография", 7: "Скальная арена", 8: "Арена изобилия",
            9: "Высший пик", 10: "Арена электричества", 11: "Электро-арена",
            12: "Механическая арена", 13: "Запретная арена", 14: "Трофейная арена",
        }
        arena_name = arena_names.get(user.arena_id, f"Арена {user.arena_id}")

    return ProfileResponse(
        player_tag=user.player_tag,
        player_name=user.player_name,
        trophies=user.trophies,
        exp_level=None,
        arena_name=arena_name,
        subscription=SubscriptionInfo(**sub_info),
    )


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
