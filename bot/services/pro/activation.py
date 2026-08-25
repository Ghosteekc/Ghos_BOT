"""Activate / extend Ghosteek Pro with Telegram Stars payment idempotency."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.database import ProPayment, Subscription, User
from bot.services.pro.entitlement import ProStatus, get_pro_status, status_from_subscription
from bot.services.pro.plans import TRIAL_DAYS, TRIAL_PLAN_ID, ProPlan, add_calendar_months, get_plan

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ProActivationResult:
    def __init__(
        self,
        *,
        activated: bool,
        duplicate: bool,
        status: ProStatus,
        message: str,
    ) -> None:
        self.activated = activated
        self.duplicate = duplicate
        self.status = status
        self.message = message


async def _get_or_create_subscription(session: AsyncSession, user: User) -> Subscription:
    result = await session.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    if sub is None:
        sub = Subscription(user_id=user.id, is_active=False, expires_at=None)
        session.add(sub)
        await session.flush()
    return sub


async def activate_pro_plan(
    session: AsyncSession,
    user: User,
    *,
    plan: ProPlan,
    payment_charge_id: str,
    provider_payment_charge_id: str | None = None,
    currency: str = "XTR",
    amount_stars: int | None = None,
    invoice_payload: str | None = None,
) -> ProActivationResult:
    """Grant/extend Pro from a confirmed Stars payment. Idempotent on charge id."""
    charge_id = (payment_charge_id or "").strip()
    if not charge_id:
        raise ValueError("payment_charge_id is required")

    existing = await session.execute(
        select(ProPayment).where(ProPayment.telegram_payment_charge_id == charge_id)
    )
    if existing.scalar_one_or_none() is not None:
        status = await get_pro_status(session, user)
        return ProActivationResult(
            activated=False,
            duplicate=True,
            status=status,
            message="Платёж уже обработан.",
        )

    now = _utc_now()
    sub = await _get_or_create_subscription(session, user)
    current = status_from_subscription(sub, now=now)

    if current.is_pro and current.expires_at is not None:
        base = _aware(current.expires_at) or now
        started = _aware(getattr(sub, "started_at", None)) or now
        expires = add_calendar_months(base, plan.months)
    elif current.is_pro and current.expires_at is None:
        started = _aware(getattr(sub, "started_at", None)) or now
        expires = None
    else:
        started = now
        expires = add_calendar_months(now, plan.months)

    sub.is_active = True
    sub.started_at = started
    sub.expires_at = expires
    sub.plan_id = plan.id
    sub.payment_id = charge_id

    payment = ProPayment(
        user_id=user.id,
        telegram_id=user.telegram_id,
        plan_id=plan.id,
        stars=int(amount_stars if amount_stars is not None else plan.stars),
        currency=currency or "XTR",
        telegram_payment_charge_id=charge_id,
        provider_payment_charge_id=provider_payment_charge_id,
        invoice_payload=invoice_payload,
        started_at=started,
        expires_at=expires,
        created_at=now,
    )
    session.add(payment)
    await session.commit()

    status = status_from_subscription(sub, now=now)
    logger.info(
        "Ghosteek Pro activated: user=%s plan=%s charge=%s expires=%s",
        user.telegram_id,
        plan.id,
        charge_id,
        expires.isoformat() if expires else "unlimited",
    )
    return ProActivationResult(
        activated=True,
        duplicate=False,
        status=status,
        message="Ghosteek Pro активирован",
    )


async def activate_pro_from_payload(
    session: AsyncSession,
    user: User,
    *,
    plan_id: str,
    payment_charge_id: str,
    provider_payment_charge_id: str | None = None,
    currency: str = "XTR",
    amount_stars: int | None = None,
    invoice_payload: str | None = None,
) -> ProActivationResult:
    plan = get_plan(plan_id)
    if plan is None:
        raise ValueError(f"Unknown plan_id: {plan_id}")
    # Never trust client/Telegram amount over catalog price for entitlement length.
    return await activate_pro_plan(
        session,
        user,
        plan=plan,
        payment_charge_id=payment_charge_id,
        provider_payment_charge_id=provider_payment_charge_id,
        currency=currency,
        amount_stars=plan.stars,
        invoice_payload=invoice_payload,
    )


async def activate_pro_trial(session: AsyncSession, user: User) -> ProActivationResult:
    """One-time free trial — full Pro access for TRIAL_DAYS."""
    sub = await _get_or_create_subscription(session, user)
    if sub.trial_used:
        status = await get_pro_status(session, user)
        return ProActivationResult(
            activated=False,
            duplicate=True,
            status=status,
            message="Пробный период уже использован.",
        )

    current = status_from_subscription(sub)
    if current.is_pro:
        status = await get_pro_status(session, user)
        return ProActivationResult(
            activated=False,
            duplicate=False,
            status=status,
            message="Ghosteek Pro уже активен.",
        )

    now = _utc_now()
    expires = now + timedelta(days=TRIAL_DAYS)
    sub.is_active = True
    sub.trial_used = True
    sub.started_at = now
    sub.expires_at = expires
    sub.plan_id = TRIAL_PLAN_ID
    sub.payment_id = None
    await session.commit()

    status = status_from_subscription(sub, now=now)
    logger.info(
        "Ghosteek Pro trial started: user=%s expires=%s",
        user.telegram_id,
        expires.isoformat(),
    )
    return ProActivationResult(
        activated=True,
        duplicate=False,
        status=status,
        message=f"Пробный Ghosteek Pro активирован на {TRIAL_DAYS} дней.",
    )


async def extend_pro_days(
    session: AsyncSession,
    user: User,
    *,
    days: int,
    plan_id: str = "referral_20d",
    commit: bool = True,
) -> ProActivationResult:
    """Extend or start Ghosteek Pro by calendar days (referral / admin grants)."""
    if days <= 0:
        raise ValueError("days must be positive")

    now = _utc_now()
    sub = await _get_or_create_subscription(session, user)
    current = status_from_subscription(sub, now=now)

    if current.is_pro and current.expires_at is None:
        # Unlimited — leave as-is, still record plan for audit.
        started = _aware(getattr(sub, "started_at", None)) or now
        expires = None
    elif current.is_pro and current.expires_at is not None:
        base = max(now, _aware(current.expires_at) or now)
        started = _aware(getattr(sub, "started_at", None)) or now
        expires = base + timedelta(days=days)
    else:
        started = now
        expires = now + timedelta(days=days)

    sub.is_active = True
    sub.started_at = started
    sub.expires_at = expires
    if not (current.is_pro and current.expires_at is None and current.plan_id == "unlimited"):
        sub.plan_id = plan_id

    if commit:
        await session.commit()
    else:
        await session.flush()

    status = status_from_subscription(sub, now=now)
    logger.info(
        "Ghosteek Pro extended: user=%s days=%s plan=%s expires=%s",
        user.telegram_id,
        days,
        plan_id,
        expires.isoformat() if expires else "unlimited",
    )
    return ProActivationResult(
        activated=True,
        duplicate=False,
        status=status,
        message=f"Ghosteek Pro продлён на {days} дн.",
    )
