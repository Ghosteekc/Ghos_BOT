import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.auth import InitDataError, validate_init_data
from bot.config import get_admin_telegram_ids, settings
from bot.models.database import User, async_session
from bot.services.clash_api import SubscriptionService
from bot.services.pro.entitlement import get_pro_status, is_user_pro
from bot.user_errors import http_error, log_error

logger = logging.getLogger(__name__)

PRO_REQUIRED = "PRO_REQUIRED"


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


def pro_required_error(feature: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "ok": False,
            "error_code": PRO_REQUIRED,
            "code": PRO_REQUIRED,
            "feature": feature,
            "message": "Эта функция доступна в Ghosteek Pro.",
        },
    )


def require_pro(feature: str) -> Callable[..., Any]:
    """Factory: backend guard for paid Ghosteek Pro features."""

    async def _dep(
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_db),
    ) -> User:
        if not await is_user_pro(session, user):
            raise pro_required_error(feature)
        return user

    return _dep


def require_pro_linked(feature: str) -> Callable[..., Any]:
    """Pro + linked Clash Royale tag."""

    async def _dep(
        user: User = Depends(require_linked_player),
        session: AsyncSession = Depends(get_db),
    ) -> User:
        if not await is_user_pro(session, user):
            raise pro_required_error(feature)
        return user

    return _dep


async def require_subscription(
    user: User = Depends(require_linked_player),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Legacy alias: linked player + active Ghosteek Pro."""
    if not await is_user_pro(session, user):
        raise pro_required_error("subscription")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.telegram_id not in get_admin_telegram_ids():
        raise http_error("E093", status=403)
    return user


async def get_subscription_info(user: User, session: AsyncSession) -> dict:
    status = await get_pro_status(session, user)
    return {
        "active": status.is_pro,
        "is_pro": status.is_pro,
        "expires_at": status.expires_at.isoformat() if status.expires_at else None,
        "started_at": status.started_at.isoformat() if status.started_at else None,
        "days_left": status.days_left,
        "trial_used": status.trial_used,
        "plan_id": status.plan_id,
        "expired": status.expired,
    }
