"""Ghosteek Pro referral status API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.deps import get_current_user, get_db
from bot.config import settings
from bot.models.database import User
from bot.services.referral.service import referral_stats_for_user

router = APIRouter(prefix="/api/referral", tags=["referral"])


class ReferralStatusOut(BaseModel):
    referral_link: str
    friends_purchased: int = 0
    credits_earned_from_referrals: int = 0
    credits_balance: int = 0
    credits_reward_amount: int = 10
    is_pro: bool
    pro_expires_at: str | None = None
    # Legacy fields (unused by Credits v2 UI)
    successful_referrals: int = 0
    current_progress: int = 0
    required_referrals: int = 0
    rewards_earned: int = 0
    reward_days: int = 0
    next_reward_in: int = 0
    days_earned_total: int = 0


def _bot_username(request: Request) -> str | None:
    cached = getattr(request.app.state, "bot_username", None)
    if cached:
        return str(cached)
    return settings.bot_username or None


@router.get("", response_model=ReferralStatusOut)
async def get_referral_status(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ReferralStatusOut:
    stats = await referral_stats_for_user(
        session,
        user,
        bot_username=_bot_username(request),
    )
    return ReferralStatusOut(
        referral_link=stats.referral_link,
        friends_purchased=stats.friends_purchased,
        credits_earned_from_referrals=stats.credits_earned_from_referrals,
        credits_balance=stats.credits_balance,
        credits_reward_amount=stats.credits_reward_amount,
        is_pro=stats.is_pro,
        pro_expires_at=stats.pro_expires_at,
        successful_referrals=stats.successful_referrals,
        current_progress=stats.current_progress,
        required_referrals=stats.required_referrals,
        rewards_earned=stats.rewards_earned,
        reward_days=stats.reward_days,
        next_reward_in=stats.next_reward_in,
        days_earned_total=stats.days_earned_total,
    )
