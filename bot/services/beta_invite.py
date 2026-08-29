"""One-time beta-tester invite links (admin-created deep links)."""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.database import BetaInvite, User
from bot.services.pro.activation import ProActivationResult, extend_pro_days

logger = logging.getLogger(__name__)

BETA_PREFIX = "beta_"
BETA_PLAN_ID = "beta_tester"
DEFAULT_BETA_DAYS = 30
MIN_BETA_DAYS = 1
MAX_BETA_DAYS = 365
# /test_30 or /test_30@BotName
_TEST_CMD_RE = re.compile(r"^/test_(\d+)(?:@\w+)?(?:\s|$)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"^[a-f0-9]{16,32}$", re.IGNORECASE)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_test_command_days(text: str | None) -> int | None:
    """Parse ``/test_30`` → 30. Returns None if not a test invite command."""
    if not text:
        return None
    m = _TEST_CMD_RE.match(text.strip())
    if not m:
        return None
    days = int(m.group(1))
    if days < MIN_BETA_DAYS or days > MAX_BETA_DAYS:
        return None
    return days


def parse_beta_payload(payload: str | None) -> str | None:
    """Parse deep-link args like ``beta_abc123…`` → token."""
    if not payload:
        return None
    raw = payload.strip()
    if not raw.startswith(BETA_PREFIX):
        return None
    token = raw[len(BETA_PREFIX) :].strip().lower()
    if not _TOKEN_RE.match(token):
        return None
    return token


def build_beta_link(*, token: str, bot_username: str | None = None) -> str:
    username = (bot_username or settings.bot_username or "").strip().lstrip("@")
    if not username:
        username = "GhosteekBot"
    return f"https://t.me/{username}?start={BETA_PREFIX}{token}"


@dataclass(frozen=True)
class CreateBetaInviteResult:
    invite: BetaInvite
    link: str


async def create_beta_invite(
    session: AsyncSession,
    *,
    created_by_telegram_id: int,
    days: int,
    bot_username: str | None = None,
) -> CreateBetaInviteResult:
    if days < MIN_BETA_DAYS or days > MAX_BETA_DAYS:
        raise ValueError(f"days must be {MIN_BETA_DAYS}–{MAX_BETA_DAYS}")

    token = secrets.token_hex(8)  # 16 hex chars
    invite = BetaInvite(
        token=token,
        days=days,
        created_by_telegram_id=created_by_telegram_id,
        created_at=_utc_now(),
    )
    session.add(invite)
    await session.commit()
    await session.refresh(invite)

    link = build_beta_link(token=token, bot_username=bot_username)
    logger.info(
        "Beta invite created: token=%s days=%s by=%s",
        token,
        days,
        created_by_telegram_id,
    )
    return CreateBetaInviteResult(invite=invite, link=link)


@dataclass(frozen=True)
class RedeemBetaInviteResult:
    ok: bool
    reason: str
    days: int = 0
    activation: ProActivationResult | None = None


async def redeem_beta_invite(
    session: AsyncSession,
    *,
    user: User,
    token: str,
) -> RedeemBetaInviteResult:
    """Claim a one-time invite: mark used then grant Pro days."""
    now = _utc_now()
    token_norm = (token or "").strip().lower()
    if not _TOKEN_RE.match(token_norm):
        return RedeemBetaInviteResult(ok=False, reason="invalid")

    # Peek first for clearer error messages (used vs missing).
    existing = await session.execute(select(BetaInvite).where(BetaInvite.token == token_norm))
    invite = existing.scalar_one_or_none()
    if invite is None:
        return RedeemBetaInviteResult(ok=False, reason="not_found")
    if invite.used_at is not None:
        return RedeemBetaInviteResult(ok=False, reason="already_used", days=invite.days)

    days = int(invite.days)
    claim = await session.execute(
        update(BetaInvite)
        .where(BetaInvite.token == token_norm, BetaInvite.used_at.is_(None))
        .values(
            used_at=now,
            used_by_telegram_id=user.telegram_id,
            used_by_user_id=user.id,
        )
    )
    if claim.rowcount != 1:
        await session.rollback()
        return RedeemBetaInviteResult(ok=False, reason="already_used", days=days)

    activation = await extend_pro_days(
        session,
        user,
        days=days,
        plan_id=BETA_PLAN_ID,
        commit=True,
    )
    logger.info(
        "Beta invite redeemed: token=%s user=%s days=%s",
        token_norm,
        user.telegram_id,
        days,
    )
    return RedeemBetaInviteResult(
        ok=True,
        reason="ok",
        days=days,
        activation=activation,
    )
