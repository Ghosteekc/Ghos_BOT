import logging
from datetime import datetime

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.auth import InitDataError, validate_init_data
from bot.config import get_admin_telegram_ids, settings
from bot.models.database import User, async_session
from bot.services.clash_api import SubscriptionService
from bot.user_errors import http_error, log_error

logger = logging.getLogger(__name__)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def get_current_user(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_db),
) -> User:
    if not x_telegram_init_data or not x_telegram_init_data.strip():
        raise http_error("E090", status=401)

    try:
        tg_user = validate_init_data(
            x_telegram_init_data,
            settings.bot_token,
            max_age_seconds=settings.init_data_max_age_seconds,
            clock_skew_seconds=settings.init_data_clock_skew_seconds,
        )
        telegram_id = int(tg_user["id"])
    except InitDataError as exc:
        log_error(logger, "E090", str(exc), exc=exc)
        code = "E091" if "истекла" in str(exc).lower() else "E090"
        raise http_error(code, status=401) from exc
    except (TypeError, ValueError) as exc:
        log_error(logger, "E090", "invalid telegram id", exc=exc)
        raise http_error("E090", status=401) from exc

    sub_service = SubscriptionService(session)
    user = await sub_service.get_or_create_user(telegram_id)
    logger.debug(
        "WebApp auth ok: telegram_id=%s user_id=%s linked=%s",
        user.telegram_id,
        user.id,
        bool(user.player_tag),
    )
    return user


async def require_linked_player(user: User = Depends(get_current_user)) -> User:
    if not user.player_tag:
        raise http_error("E092", status=403)
    return user


async def require_subscription(
    user: User = Depends(require_linked_player),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Требует привязанный тег; подписка сейчас бесплатная для всех."""
    sub_service = SubscriptionService(session)
    if not await sub_service.has_active_subscription(user):
        raise http_error("E093", status=403, message="Подписка не активна.")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.telegram_id not in get_admin_telegram_ids():
        raise http_error("E093", status=403)
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
