"""Read-only preflight for a future, policy-gated account deletion flow.

This module deliberately has no delete/update path and is not exposed by an API.
It inventories the current ORM relationships before any destructive design is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.database import (
    BattleCache,
    BetaInvite,
    CardPreference,
    CreditTransaction,
    FavoriteDeck,
    MetaBattleObservation,
    ProPayment,
    ProReminderSent,
    Referral,
    ReferralReward,
    Subscription,
    TrackedMineDeck,
    User,
    UserSettings,
    WeeklyDigestSent,
)
from bot.services.pro.entitlement import admin_pro_status, is_admin_pro_user, status_from_subscription

DeletionMode = Literal["now", "after_pro"]


@dataclass(frozen=True)
class DeletionPreflight:
    """Counts and gates only; never a promise that deletion has happened."""

    account_found: bool
    mode: DeletionMode
    pro_active: bool
    not_before: datetime | None
    row_counts: dict[str, int]
    blockers: tuple[str, ...]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _count(session: AsyncSession, model: type, *where: object) -> int:
    result = await session.scalar(select(func.count()).select_from(model).where(*where))
    return int(result or 0)


async def inspect_account_deletion(
    session: AsyncSession,
    *,
    user_id: int,
    mode: DeletionMode,
    now: datetime | None = None,
) -> DeletionPreflight:
    """Inspect one existing account without creating users, committing, or changing rows.

    This internal function accepts a database user ID, not a caller-supplied API target.
    A future route must derive that ID from validated Telegram init data.
    """
    if mode not in ("now", "after_pro"):
        raise ValueError("Unsupported deletion mode")
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("Deletion preflight requires a clean session")
    current = _aware(now) or datetime.now(timezone.utc)
    user = await session.get(User, user_id)
    if user is None:
        return DeletionPreflight(False, mode, False, None, {}, ("account_absent",))

    subscription = await session.scalar(select(Subscription).where(Subscription.user_id == user.id))
    pro = admin_pro_status() if is_admin_pro_user(user) else status_from_subscription(subscription, now=current)
    not_before = current if mode == "now" or not pro.is_pro else _aware(pro.expires_at)

    owned = (
        ("settings", UserSettings, UserSettings.user_id == user.id),
        ("subscription", Subscription, Subscription.user_id == user.id),
        ("payments", ProPayment, ProPayment.user_id == user.id),
        ("card_preferences", CardPreference, CardPreference.user_id == user.id),
        ("favorite_decks", FavoriteDeck, FavoriteDeck.user_id == user.id),
        ("tracked_decks", TrackedMineDeck, TrackedMineDeck.user_id == user.id),
        ("weekly_digests", WeeklyDigestSent, WeeklyDigestSent.user_id == user.id),
        ("pro_reminders", ProReminderSent, ProReminderSent.user_id == user.id),
        ("referral_rewards", ReferralReward, ReferralReward.referrer_user_id == user.id),
        ("referrals_as_referrer", Referral, Referral.referrer_user_id == user.id),
        ("referrals_as_referred", Referral, Referral.referred_user_id == user.id),
        ("credits_owned", CreditTransaction, CreditTransaction.user_id == user.id),
        ("credits_sourced", CreditTransaction, CreditTransaction.source_user_id == user.id),
        ("invites", BetaInvite, or_(
            BetaInvite.used_by_user_id == user.id,
            BetaInvite.used_by_telegram_id == user.telegram_id,
            BetaInvite.created_by_telegram_id == user.telegram_id,
        )),
    )
    counts = {name: await _count(session, model, condition) for name, model, condition in owned}
    counts["battle_cache_for_linked_tag"] = (
        await _count(session, BattleCache, BattleCache.player_tag == user.player_tag)
        if user.player_tag else 0
    )
    counts["shared_meta_for_linked_tag"] = (
        await _count(session, MetaBattleObservation, or_(
            MetaBattleObservation.player_tag == user.player_tag,
            MetaBattleObservation.opponent_tag == user.player_tag,
        )) if user.player_tag else 0
    )

    blockers = ["retention_policy_unapproved", "backup_restore_guard_missing", "destructive_flow_disabled"]
    if mode == "after_pro" and pro.is_pro and not_before is None:
        blockers.append("pro_has_no_finite_expiry")
    if counts["payments"]:
        blockers.append("payment_records_attached_to_user")
    if any(counts[key] for key in (
        "referral_rewards", "referrals_as_referrer", "referrals_as_referred",
        "credits_owned", "credits_sourced", "invites",
    )):
        blockers.append("shared_ledger_requires_separation")
    if counts["battle_cache_for_linked_tag"] or counts["shared_meta_for_linked_tag"]:
        blockers.append("tag_data_provenance_unverified")
    blockers.append("fsm_and_replay_ownership_unverified")
    return DeletionPreflight(True, mode, pro.is_pro, not_before, counts, tuple(blockers))
