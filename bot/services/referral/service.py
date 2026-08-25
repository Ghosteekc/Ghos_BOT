"""Referral conversions and Pro day rewards (5 friends → +20 days)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.database import Referral, ReferralReward, User
from bot.services.pro.activation import extend_pro_days
from bot.services.pro.entitlement import get_pro_status
from bot.services.pro.plans import (
    REFERRAL_DISCOUNT_STARS,
    REFERRAL_DISCOUNT_WINDOW_DAYS,
    get_plan_stars,
)

logger = logging.getLogger(__name__)

REFERRAL_PREFIX = "ref_"
REQUIRED_REFERRALS = 5
REWARD_DAYS = 20
REFERRAL_PLAN_ID = "referral_20d"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class InviteeDiscount:
    """Active purchase discount for a user who registered via referral."""

    active: bool
    expires_at: datetime | None
    prices: dict[str, int]


@dataclass(frozen=True)
class ReferralStats:
    referral_link: str
    successful_referrals: int
    current_progress: int
    required_referrals: int
    rewards_earned: int
    reward_days: int
    next_reward_in: int
    days_earned_total: int
    is_pro: bool
    pro_expires_at: str | None


@dataclass(frozen=True)
class ConversionResult:
    accepted: bool
    reason: str
    rewards_granted: int = 0


def parse_referral_payload(payload: str | None) -> int | None:
    """Parse deep-link args like ``ref_123456789`` → referrer telegram_id."""
    if not payload:
        return None
    raw = payload.strip()
    if not raw.startswith(REFERRAL_PREFIX):
        return None
    token = raw[len(REFERRAL_PREFIX) :].strip()
    if not token.isdigit():
        return None
    try:
        value = int(token)
    except ValueError:
        return None
    return value if value > 0 else None


def build_referral_link(*, telegram_id: int, bot_username: str | None = None) -> str:
    username = (bot_username or settings.bot_username or "").strip().lstrip("@")
    if not username:
        username = "GhosteekBot"
    return f"https://t.me/{username}?start={REFERRAL_PREFIX}{telegram_id}"


async def get_invitee_discount(session: AsyncSession, user: User) -> InviteeDiscount:
    """Discount for referred users within 30 days of successful referral registration."""
    res = await session.execute(select(Referral).where(Referral.referred_user_id == user.id))
    row = res.scalar_one_or_none()
    if row is None:
        return InviteeDiscount(active=False, expires_at=None, prices={})

    created = _aware(row.created_at) or _utc_now()
    expires = created + timedelta(days=REFERRAL_DISCOUNT_WINDOW_DAYS)
    now = _utc_now()
    if now >= expires:
        return InviteeDiscount(active=False, expires_at=expires, prices={})

    return InviteeDiscount(
        active=True,
        expires_at=expires,
        prices=dict(REFERRAL_DISCOUNT_STARS),
    )


async def resolve_plan_stars(session: AsyncSession, user: User, plan_id: str) -> int | None:
    """Stars amount the user must pay for ``plan_id`` right now."""
    discount = await get_invitee_discount(session, user)
    return get_plan_stars(plan_id, referral_discount=discount.active)


async def _count_referrals(session: AsyncSession, referrer_user_id: int) -> int:
    res = await session.execute(
        select(func.count()).select_from(Referral).where(Referral.referrer_user_id == referrer_user_id)
    )
    return int(res.scalar_one() or 0)


async def _count_rewards(session: AsyncSession, referrer_user_id: int) -> int:
    res = await session.execute(
        select(func.count())
        .select_from(ReferralReward)
        .where(ReferralReward.referrer_user_id == referrer_user_id)
    )
    return int(res.scalar_one() or 0)


async def _unconsumed_referrals(session: AsyncSession, referrer_user_id: int) -> list[Referral]:
    res = await session.execute(
        select(Referral)
        .where(Referral.referrer_user_id == referrer_user_id)
        .where(Referral.reward_id.is_(None))
        .order_by(Referral.id.asc())
    )
    return list(res.scalars().all())


async def _grant_pending_rewards(session: AsyncSession, referrer: User) -> int:
    """Consume unrewarded referrals in batches of 5. Idempotent via reward_id."""
    granted = 0
    while True:
        pending = await _unconsumed_referrals(session, referrer.id)
        if len(pending) < REQUIRED_REFERRALS:
            break
        batch = pending[:REQUIRED_REFERRALS]
        batch_ids = [row.id for row in batch]

        activation = await extend_pro_days(
            session,
            referrer,
            days=REWARD_DAYS,
            plan_id=REFERRAL_PLAN_ID,
            commit=False,
        )
        reward = ReferralReward(
            referrer_user_id=referrer.id,
            days_granted=REWARD_DAYS,
            referrals_consumed=REQUIRED_REFERRALS,
            created_at=datetime.now(timezone.utc),
            expires_at_after=activation.status.expires_at,
        )
        session.add(reward)
        await session.flush()

        result = await session.execute(
            update(Referral)
            .where(Referral.id.in_(batch_ids))
            .where(Referral.reward_id.is_(None))
            .values(reward_id=reward.id)
        )
        attached = int(result.rowcount or 0)
        if attached < REQUIRED_REFERRALS:
            await session.delete(reward)
            await session.flush()
            break

        granted += 1
        logger.info(
            "Referral reward granted: referrer=%s days=%s reward_id=%s",
            referrer.telegram_id,
            REWARD_DAYS,
            reward.id,
        )
    return granted


async def process_referral_conversion(
    session: AsyncSession,
    *,
    referred_user: User,
    referrer_telegram_id: int | None,
    is_new_user: bool,
) -> ConversionResult:
    """Register a referral after first-time user creation. Click alone does not count."""
    if referrer_telegram_id is None:
        return ConversionResult(accepted=False, reason="no_payload")
    if not is_new_user:
        return ConversionResult(accepted=False, reason="existing_user")
    if referrer_telegram_id == referred_user.telegram_id:
        return ConversionResult(accepted=False, reason="self_referral")

    res = await session.execute(select(User).where(User.telegram_id == referrer_telegram_id))
    referrer = res.scalar_one_or_none()
    if referrer is None:
        return ConversionResult(accepted=False, reason="referrer_not_found")
    if referrer.id == referred_user.id:
        return ConversionResult(accepted=False, reason="self_referral")

    existing = await session.execute(
        select(Referral.id).where(Referral.referred_user_id == referred_user.id)
    )
    if existing.scalar_one_or_none() is not None:
        return ConversionResult(accepted=False, reason="already_referred")

    row = Referral(
        referrer_user_id=referrer.id,
        referred_user_id=referred_user.id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return ConversionResult(accepted=False, reason="already_referred")

    rewards = await _grant_pending_rewards(session, referrer)
    await session.commit()
    return ConversionResult(accepted=True, reason="ok", rewards_granted=rewards)


async def referral_stats_for_user(
    session: AsyncSession,
    user: User,
    *,
    bot_username: str | None = None,
) -> ReferralStats:
    total = await _count_referrals(session, user.id)
    rewards = await _count_rewards(session, user.id)
    pending = len(await _unconsumed_referrals(session, user.id))
    # Drain any leftover batches (e.g. after crash between insert and grant).
    if pending >= REQUIRED_REFERRALS:
        await _grant_pending_rewards(session, user)
        await session.commit()
        total = await _count_referrals(session, user.id)
        rewards = await _count_rewards(session, user.id)
        pending = len(await _unconsumed_referrals(session, user.id))

    current_progress = pending
    next_in = REQUIRED_REFERRALS - current_progress if current_progress else REQUIRED_REFERRALS

    status = await get_pro_status(session, user)
    return ReferralStats(
        referral_link=build_referral_link(
            telegram_id=user.telegram_id,
            bot_username=bot_username,
        ),
        successful_referrals=total,
        current_progress=current_progress,
        required_referrals=REQUIRED_REFERRALS,
        rewards_earned=rewards,
        reward_days=REWARD_DAYS,
        next_reward_in=next_in,
        days_earned_total=rewards * REWARD_DAYS,
        is_pro=status.is_pro,
        pro_expires_at=status.expires_at.isoformat() if status.expires_at else None,
    )
