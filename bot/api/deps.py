import logging
from datetime import datetime

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.auth import InitDataError, validate_init_data
from bot.config import settings
from bot.models.database import User, async_session
from bot.services.clash_api import SubscriptionService

logger = logging.getLogger(__name__)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def get_current_user(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_db),
) -> User:
    logger.info(f"WebApp auth attempt: initData length={len(x_telegram_init_data)}, first_100={x_telegram_init_data[:100]!r}")
    try:
        tg_user = validate_init_data(x_telegram_init_data, settings.bot_token)
        telegram_id = int(tg_user["id"])
        logger.info(f"WebApp auth success: telegram_id={telegram_id}, username={tg_user.get('username')}")
    except InitDataError as e:
        logger.error(f"WebApp auth failed: {e}, initData preview={x_telegram_init_data[:200]!r}")
        raise HTTPException(status_code=401, detail=str(e)) from e

    sub_service = SubscriptionService(session)
    user = await sub_service.get_or_create_user(telegram_id)
    logger.info(f"WebApp user: id={user.id}, telegram_id={user.telegram_id}, player_tag={user.player_tag}")
    return user


async def require_linked_player(user: User = Depends(get_current_user)) -> User:
    if not user.player_tag:
        raise HTTPException(
            status_code=403,
            detail="Player tag not linked. Use /link #TAG in the bot chat.",
        )
    return user


async def require_subscription(
    user: User = Depends(require_linked_player),
    session: AsyncSession = Depends(get_db),
) -> User:
    sub_service = SubscriptionService(session)
    if not await sub_service.has_active_subscription(user):
        raise HTTPException(
            status_code=402,
            detail="Subscription required. Use /subscribe in the bot chat.",
        )
    return user


async def get_subscription_info(user: User, session: AsyncSession) -> dict:
    sub_service = SubscriptionService(session)
    info = await sub_service.get_subscription_info(user)
    expires = info["expires_at"]
    return {
        "active": info["active"],
        "expires_at": expires.isoformat() if isinstance(expires, datetime) else None,
        "trial_used": info["trial_used"],
    }
