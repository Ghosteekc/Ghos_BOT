"""Ghosteek Pro entitlement — single source of truth for access checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.database import Subscription, User


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class ProStatus:
    is_pro: bool
    started_at: datetime | None
    expires_at: datetime | None
    days_left: int | None
    plan_id: str | None
    trial_used: bool
    expired: bool

    def to_dict(self) -> dict:
        return {
            "is_pro": self.is_pro,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "days_left": self.days_left,
            "plan_id": self.plan_id,
            "trial_used": self.trial_used,
            "expired": self.expired,
            # Backward-compatible aliases used by /api/me
            "active": self.is_pro,
        }


def status_from_subscription(sub: Subscription | None, *, now: datetime | None = None) -> ProStatus:
    now_dt = _aware(now) or _utc_now()
    assert now_dt is not None
    now = now_dt
    if sub is None:
        return ProStatus(
            is_pro=False,
            started_at=None,
            expires_at=None,
            days_left=None,
            plan_id=None,
            trial_used=False,
            expired=False,
        )

    expires = _aware(sub.expires_at)
    started = _aware(getattr(sub, "started_at", None))
    plan_id = getattr(sub, "plan_id", None)
    trial_used = bool(sub.trial_used)

    # Unlimited admin grant only when explicitly marked
    if sub.is_active and expires is None and plan_id == "unlimited":
        return ProStatus(
            is_pro=True,
            started_at=started,
            expires_at=None,
            days_left=None,
            plan_id=plan_id,
            trial_used=trial_used,
            expired=False,
        )

    if not sub.is_active or expires is None:
        expired = bool(expires and expires <= now)
        return ProStatus(
            is_pro=False,
            started_at=started,
            expires_at=expires,
            days_left=0 if expired else None,
            plan_id=plan_id,
            trial_used=trial_used,
            expired=expired,
        )

    if expires <= now:
        return ProStatus(
            is_pro=False,
            started_at=started,
            expires_at=expires,
            days_left=0,
            plan_id=plan_id,
            trial_used=trial_used,
            expired=True,
        )

    seconds = (expires - now).total_seconds()
    days_left = max(1, ceil(seconds / 86400.0)) if seconds > 0 else 0
    return ProStatus(
        is_pro=True,
        started_at=started,
        expires_at=expires,
        days_left=days_left,
        plan_id=plan_id,
        trial_used=trial_used,
        expired=False,
    )


async def get_subscription_row(session: AsyncSession, user: User) -> Subscription | None:
    result = await session.execute(select(Subscription).where(Subscription.user_id == user.id))
    return result.scalar_one_or_none()


async def get_pro_status(session: AsyncSession, user: User) -> ProStatus:
    sub = await get_subscription_row(session, user)
    status = status_from_subscription(sub)
    # Lazy deactivate expired rows so UI/DB stay consistent after restart
    if sub is not None and status.expired and sub.is_active:
        sub.is_active = False
        await session.commit()
    return status


async def is_user_pro(session: AsyncSession, user: User) -> bool:
    return (await get_pro_status(session, user)).is_pro
