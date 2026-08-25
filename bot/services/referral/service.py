"""Referral attributions + invitee discount (Credits granted on first Pro purchase)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.database import CreditTransaction, ProPayment, Referral, User
from bot.services.credits import (
    TYPE_REFERRAL_FRIEND_REWARD,
    TYPE_REFERRAL_REWARD,
    credit_once,
    get_credits_balance,
)
from bot.services.pro.entitlement import get_pro_status
from bot.services.pro.plans import get_plan, get_plan_stars, referral_discount_window_days
from bot.services.pro.pricing import (
    PurchaseQuote,
    build_purchase_quote,
    discount_percent_config,
)

logger = logging.getLogger(__name__)

REFERRAL_PREFIX = "ref_"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def referral_credits_reward() -> int:
    return max(1, int(getattr(settings, "referral_credits_reward", 10) or 10))


@dataclass(frozen=True)
class InviteeDiscount:
    """First-purchase referral % discount while window is open and unpaid."""

    active: bool
    expires_at: datetime | None
    percent: int
    prices: dict[str, int]


@dataclass(frozen=True)
class ReferralStats:
    referral_link: str
    friends_purchased: int
    credits_earned_from_referrals: int
    credits_balance: int
    credits_reward_amount: int
    is_pro: bool
    pro_expires_at: str | None
    # Backward-compatible aliases for older clients
    successful_referrals: int = 0
    current_progress: int = 0
    required_referrals: int = 0
    rewards_earned: int = 0
    reward_days: int = 0
    next_reward_in: int = 0
    days_earned_total: int = 0


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


async def _has_paid_pro(session: AsyncSession, user_id: int) -> bool:
    res = await session.execute(
        select(func.count()).select_from(ProPayment).where(ProPayment.user_id == user_id)
    )
    return int(res.scalar_one() or 0) > 0


async def get_invitee_discount(session: AsyncSession, user: User) -> InviteeDiscount:
    """% discount for referred users before their first paid Pro purchase (within window)."""
    res = await session.execute(select(Referral).where(Referral.referred_user_id == user.id))
    row = res.scalar_one_or_none()
    if row is None:
        return InviteeDiscount(active=False, expires_at=None, percent=0, prices={})

    created = _aware(row.created_at) or _utc_now()
    expires = created + timedelta(days=referral_discount_window_days())
    now = _utc_now()
    if now >= expires:
        return InviteeDiscount(active=False, expires_at=expires, percent=0, prices={})
    if row.first_purchase_at is not None or await _has_paid_pro(session, user.id):
        return InviteeDiscount(active=False, expires_at=expires, percent=0, prices={})

    pct = discount_percent_config()
    prices: dict[str, int] = {}
    for plan_id in ("pro_1m", "pro_3m", "pro_6m"):
        stars = get_plan_stars(plan_id, referral_discount=True)
        if stars is not None:
            prices[plan_id] = stars

    return InviteeDiscount(active=True, expires_at=expires, percent=pct, prices=prices)


async def quote_plan_purchase(
    session: AsyncSession,
    user: User,
    plan_id: str,
) -> PurchaseQuote | None:
    if get_plan(plan_id) is None:
        return None
    discount = await get_invitee_discount(session, user)
    balance = await get_credits_balance(session, user.id)
    return build_purchase_quote(
        plan_id=plan_id,
        referral_discount=discount.active,
        available_credits=balance,
        discount_percent=discount.percent if discount.active else 0,
    )


async def resolve_plan_stars(session: AsyncSession, user: User, plan_id: str) -> int | None:
    """Stars the user must pay for ``plan_id`` right now (after discount + Credits)."""
    quote = await quote_plan_purchase(session, user, plan_id)
    return quote.stars_to_pay if quote else None


async def process_referral_conversion(
    session: AsyncSession,
    *,
    referred_user: User,
    referrer_telegram_id: int | None,
    is_new_user: bool,
) -> ConversionResult:
    """Attribute referral on first-time registration. No Credits yet."""
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
        created_at=_utc_now(),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return ConversionResult(accepted=False, reason="already_referred")

    await session.commit()
    return ConversionResult(accepted=True, reason="ok", rewards_granted=0)


async def grant_referral_purchase_credits(
    session: AsyncSession,
    buyer: User,
    *,
    payment_charge_id: str,
) -> bool:
    """After invitee's first successful Pro purchase: +N Credits to both sides (once)."""
    res = await session.execute(select(Referral).where(Referral.referred_user_id == buyer.id))
    row = res.scalar_one_or_none()
    if row is None:
        return False

    amount = referral_credits_reward()
    ref_key = f"ref_buy:{row.id}:referrer"
    friend_key = f"ref_buy:{row.id}:invitee"

    granted_ref = await credit_once(
        session,
        user_id=row.referrer_user_id,
        amount=amount,
        tx_type=TYPE_REFERRAL_REWARD,
        reference_id=ref_key,
        source_user_id=buyer.id,
    )
    granted_friend = await credit_once(
        session,
        user_id=buyer.id,
        amount=amount,
        tx_type=TYPE_REFERRAL_FRIEND_REWARD,
        reference_id=friend_key,
        source_user_id=row.referrer_user_id,
    )

    if row.first_purchase_at is None:
        row.first_purchase_at = _utc_now()

    if granted_ref or granted_friend:
        logger.info(
            "Referral purchase credits: referral_id=%s charge=%s ref=%s friend=%s",
            row.id,
            payment_charge_id,
            granted_ref,
            granted_friend,
        )
    return granted_ref or granted_friend


async def referral_stats_for_user(
    session: AsyncSession,
    user: User,
    *,
    bot_username: str | None = None,
) -> ReferralStats:
    purchased_res = await session.execute(
        select(func.count())
        .select_from(Referral)
        .where(Referral.referrer_user_id == user.id)
        .where(Referral.first_purchase_at.is_not(None))
    )
    friends_purchased = int(purchased_res.scalar_one() or 0)
    reward = referral_credits_reward()
    earned_res = await session.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
            CreditTransaction.user_id == user.id,
            CreditTransaction.type == TYPE_REFERRAL_REWARD,
        )
    )
    credits_earned = max(0, int(earned_res.scalar_one() or 0))
    balance = await get_credits_balance(session, user.id)
    status = await get_pro_status(session, user)

    return ReferralStats(
        referral_link=build_referral_link(
            telegram_id=user.telegram_id,
            bot_username=bot_username,
        ),
        friends_purchased=friends_purchased,
        credits_earned_from_referrals=credits_earned,
        credits_balance=balance,
        credits_reward_amount=reward,
        is_pro=status.is_pro,
        pro_expires_at=status.expires_at.isoformat() if status.expires_at else None,
        successful_referrals=friends_purchased,
        current_progress=friends_purchased,
        required_referrals=0,
        rewards_earned=friends_purchased,
        reward_days=0,
        next_reward_in=0,
        days_earned_total=0,
    )
