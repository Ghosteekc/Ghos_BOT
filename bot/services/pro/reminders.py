"""Telegram reminders before Ghosteek Pro expires."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.database import ProReminderSent, Subscription, User, UserSettings, async_session
from bot.services.pro.entitlement import get_pro_status, is_admin_pro_user
from bot.services.pro.plans import TRIAL_PLAN_ID

logger = logging.getLogger(__name__)

REMINDER_RENEW_2D = "renew_2d"
REMINDER_TRIAL_LAST = "trial_last_day"

CHECK_INTERVAL_SEC = 6 * 3600


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _period_key(expires_at: datetime) -> str:
    dt = expires_at.astimezone(timezone.utc)
    return dt.date().isoformat()


def _format_expiry(expires_at: datetime) -> str:
    return expires_at.astimezone(timezone.utc).strftime("%d.%m.%Y")


def _pro_keyboard(label: str = "Открыть Ghosteek Pro") -> InlineKeyboardMarkup | None:
    webapp = (settings.webapp_url or "").strip().rstrip("/")
    if not webapp or "your-domain" in webapp or not webapp.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    web_app=WebAppInfo(url=f"{webapp}/pro"),
                )
            ]
        ]
    )


def _renew_message(expires_at: datetime, days_left: int) -> str:
    until = _format_expiry(expires_at)
    return (
        "⏳ <b>Ghosteek Pro скоро закончится</b>\n\n"
        f"Подписка активна ещё {days_left} "
        f"{'день' if days_left == 1 else 'дня' if 2 <= days_left <= 4 else 'дней'} — до {until}.\n\n"
        "Продлите Pro в Mini App, чтобы сохранить AI-тренер, мету и разбор боёв."
    )


def _trial_last_day_message(expires_at: datetime) -> str:
    until = _format_expiry(expires_at)
    return (
        "✨ <b>Последний день пробного Pro</b>\n\n"
        f"Сегодня заканчивается ваш 7-дневный пробный период ({until}).\n\n"
        "Понравилось? Оформите подписку и сохраните доступ ко всем Pro-функциям."
    )


async def _notifications_enabled(session: AsyncSession, user: User) -> bool:
    res = await session.execute(
        select(UserSettings.telegram_notifications).where(UserSettings.user_id == user.id)
    )
    row = res.scalar_one_or_none()
    if row is None:
        return True
    return bool(row)


async def _already_sent(session: AsyncSession, user_id: int, kind: str, period_key: str) -> bool:
    res = await session.execute(
        select(ProReminderSent.id).where(
            ProReminderSent.user_id == user_id,
            ProReminderSent.kind == kind,
            ProReminderSent.period_key == period_key,
        )
    )
    return res.scalar_one_or_none() is not None


async def _mark_sent(session: AsyncSession, user_id: int, kind: str, period_key: str) -> None:
    session.add(
        ProReminderSent(
            user_id=user_id,
            kind=kind,
            period_key=period_key,
            sent_at=_utc_now(),
        )
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()


async def _send_reminder(bot: Bot, user: User, text: str, *, button_label: str) -> bool:
    try:
        await bot.send_message(
            user.telegram_id,
            text,
            reply_markup=_pro_keyboard(button_label),
        )
        return True
    except TelegramForbiddenError:
        logger.info("Pro reminder blocked telegram_id=%s", user.telegram_id)
        return False
    except TelegramRetryAfter:
        raise
    except Exception:
        logger.exception("Pro reminder send failed telegram_id=%s", user.telegram_id)
        return False


async def run_reminder_cycle(bot: Bot) -> int:
    sent = 0
    async with async_session() as session:
        res = await session.execute(
            select(User, Subscription)
            .join(Subscription, Subscription.user_id == User.id)
            .where(Subscription.is_active.is_(True))
            .where(Subscription.expires_at.is_not(None))
        )
        rows = list(res.all())

    for user, _sub in rows:
        if is_admin_pro_user(user):
            continue
        async with async_session() as session:
            if not await _notifications_enabled(session, user):
                continue
            status = await get_pro_status(session, user)
            if not status.is_pro or status.expires_at is None or status.days_left is None:
                continue
            if status.plan_id in ("admin", "unlimited"):
                continue

            period = _period_key(status.expires_at)
            days_left = status.days_left

            kind: str | None = None
            text: str | None = None
            button = "Открыть Ghosteek Pro"

            if status.plan_id == TRIAL_PLAN_ID and days_left == 1:
                kind = REMINDER_TRIAL_LAST
                text = _trial_last_day_message(status.expires_at)
                button = "Выбрать тариф"
            elif status.plan_id != TRIAL_PLAN_ID and days_left == 2:
                kind = REMINDER_RENEW_2D
                text = _renew_message(status.expires_at, days_left)

            if not kind or not text:
                continue
            if await _already_sent(session, user.id, kind, period):
                continue

            try:
                if await _send_reminder(bot, user, text, button_label=button):
                    await _mark_sent(session, user.id, kind, period)
                    sent += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(float(exc.retry_after) + 0.5)
                if await _send_reminder(bot, user, text, button_label=button):
                    await _mark_sent(session, user.id, kind, period)
                    sent += 1

        await asyncio.sleep(0.05)

    return sent


async def run_periodic(bot: Bot, stop_event: asyncio.Event) -> None:
    logger.info("Ghosteek Pro reminder loop started (every %sh)", CHECK_INTERVAL_SEC // 3600)
    while not stop_event.is_set():
        try:
            count = await run_reminder_cycle(bot)
            if count:
                logger.info("Pro reminders sent: %s", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Pro reminder cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL_SEC)
            return
        except asyncio.TimeoutError:
            continue
