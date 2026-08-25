"""Ghosteek Credits ledger (internal Pro discount only — not transferable)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.database import CreditTransaction

logger = logging.getLogger(__name__)

TYPE_REFERRAL_REWARD = "referral_reward"
TYPE_REFERRAL_FRIEND_REWARD = "referral_friend_reward"
TYPE_SUBSCRIPTION_DISCOUNT = "subscription_discount"
TYPE_MANUAL_ADJUSTMENT = "manual_adjustment"
TYPE_REFUND = "refund"
TYPE_REVERSAL = "reversal"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def get_credits_balance(session: AsyncSession, user_id: int) -> int:
    res = await session.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
            CreditTransaction.user_id == user_id
        )
    )
    return max(0, int(res.scalar_one() or 0))


async def credit_once(
    session: AsyncSession,
    *,
    user_id: int,
    amount: int,
    tx_type: str,
    reference_id: str,
    source_user_id: int | None = None,
) -> bool:
    """Grant credits if ``reference_id`` is new. Returns True when a new row was written."""
    if amount <= 0:
        raise ValueError("credit amount must be positive")
    reference_id = (reference_id or "").strip()
    if not reference_id:
        raise ValueError("reference_id is required")

    existing = await session.execute(
        select(CreditTransaction.id).where(CreditTransaction.reference_id == reference_id)
    )
    if existing.scalar_one_or_none() is not None:
        return False

    row = CreditTransaction(
        user_id=user_id,
        amount=int(amount),
        type=tx_type,
        source_user_id=source_user_id,
        reference_id=reference_id,
        created_at=_utc_now(),
    )
    session.add(row)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        return False
    logger.info(
        "Credits granted user=%s amount=%s type=%s ref=%s",
        user_id,
        amount,
        tx_type,
        reference_id,
    )
    return True


async def spend_credits_once(
    session: AsyncSession,
    *,
    user_id: int,
    amount: int,
    reference_id: str,
) -> bool:
    """Spend credits idempotently. True = newly spent; False = already spent for this ref.

    Raises ValueError on insufficient balance when this is a new spend.
    """
    if amount < 0:
        raise ValueError("spend amount must be >= 0")
    if amount == 0:
        return False
    reference_id = (reference_id or "").strip()
    if not reference_id:
        raise ValueError("reference_id is required")

    existing = await session.execute(
        select(CreditTransaction.id).where(CreditTransaction.reference_id == reference_id)
    )
    if existing.scalar_one_or_none() is not None:
        return False

    balance = await get_credits_balance(session, user_id)
    if balance < amount:
        raise ValueError("insufficient_credits")

    row = CreditTransaction(
        user_id=user_id,
        amount=-int(amount),
        type=TYPE_SUBSCRIPTION_DISCOUNT,
        source_user_id=None,
        reference_id=reference_id,
        created_at=_utc_now(),
    )
    session.add(row)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        return False
    logger.info("Credits spent user=%s amount=%s ref=%s", user_id, amount, reference_id)
    return True
