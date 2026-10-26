"""Read-only deletion planning tests; all records are fictional and in memory."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.models.database import (
    Base, BattleCache, CreditTransaction, MetaBattleObservation, ProPayment,
    Referral, Subscription, User,
)
from bot.services.account_deletion import inspect_account_deletion


async def _isolated_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def test_active_pro_payment_referral_and_shared_data_are_only_inspected() -> None:
    async def run() -> None:
        engine, sessions = await _isolated_db()
        try:
            now = datetime(2026, 10, 26, tzinfo=timezone.utc)
            expiry = now + timedelta(days=20)
            async with sessions() as session:
                inviter = User(telegram_id=901001)
                member = User(telegram_id=901002, player_tag="#TEST123", player_name="Fixture")
                session.add_all((inviter, member))
                await session.flush()
                session.add_all((
                    Subscription(user_id=member.id, is_active=True, started_at=now, expires_at=expiry),
                    ProPayment(
                        user_id=member.id, telegram_id=member.telegram_id, plan_id="test_plan",
                        stars=250, telegram_payment_charge_id="fictional-charge",
                    ),
                    Referral(referrer_user_id=inviter.id, referred_user_id=member.id),
                    CreditTransaction(
                        user_id=inviter.id, source_user_id=member.id, amount=10,
                        type="test_reward", reference_id="fictional-referral",
                    ),
                    BattleCache(
                        player_tag=member.player_tag, battle_time="fictional-time", result="win",
                        user_deck="", opponent_deck="",
                    ),
                    MetaBattleObservation(
                        dedupe_key="fictional-observation", player_tag=member.player_tag,
                        battle_time="fictional-time", mode="trophies", deck_hash="fixture",
                        result="win",
                    ),
                ))
                await session.commit()

                now_plan = await inspect_account_deletion(session, user_id=member.id, mode="now", now=now)
                later_plan = await inspect_account_deletion(session, user_id=member.id, mode="after_pro", now=now)

                assert now_plan.account_found and now_plan.pro_active
                assert now_plan.not_before == now
                assert later_plan.not_before == expiry
                assert later_plan.row_counts["payments"] == 1
                assert later_plan.row_counts["referrals_as_referred"] == 1
                assert later_plan.row_counts["credits_sourced"] == 1
                assert later_plan.row_counts["battle_cache_for_linked_tag"] == 1
                assert later_plan.row_counts["shared_meta_for_linked_tag"] == 1
                assert "payment_records_attached_to_user" in later_plan.blockers
                assert "shared_ledger_requires_separation" in later_plan.blockers
                assert "destructive_flow_disabled" in later_plan.blockers
                assert not session.new and not session.dirty and not session.deleted
                assert await session.scalar(select(func.count()).select_from(ProPayment)) == 1
                assert await session.scalar(select(func.count()).select_from(CreditTransaction)) == 1
                assert await session.scalar(select(func.count()).select_from(MetaBattleObservation)) == 1

                # A later purchase may extend Pro; a fresh preflight must use the new date.
                sub = await session.scalar(select(Subscription).where(Subscription.user_id == member.id))
                assert sub is not None
                sub.expires_at = expiry + timedelta(days=30)
                await session.commit()
                revised = await inspect_account_deletion(session, user_id=member.id, mode="after_pro", now=now)
                assert revised.not_before == expiry + timedelta(days=30)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_absent_account_is_not_created_and_nonexpiring_pro_is_blocked() -> None:
    async def run() -> None:
        engine, sessions = await _isolated_db()
        try:
            async with sessions() as session:
                missing = await inspect_account_deletion(session, user_id=999, mode="now")
                assert not missing.account_found
                assert missing.blockers == ("account_absent",)
                assert await session.scalar(select(func.count()).select_from(User)) == 0

                user = User(telegram_id=901003)
                session.add(user)
                await session.flush()
                session.add(Subscription(user_id=user.id, is_active=True, plan_id="unlimited"))
                await session.commit()
                plan = await inspect_account_deletion(session, user_id=user.id, mode="after_pro")
                assert plan.pro_active and plan.not_before is None
                assert "pro_has_no_finite_expiry" in plan.blockers
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_invalid_mode_is_rejected_before_any_lookup() -> None:
    async def run() -> None:
        engine, sessions = await _isolated_db()
        try:
            async with sessions() as session:
                try:
                    await inspect_account_deletion(session, user_id=1, mode="invalid")  # type: ignore[arg-type]
                except ValueError:
                    pass
                else:
                    raise AssertionError("An unsupported deletion mode was accepted")
                assert await session.scalar(select(func.count()).select_from(User)) == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_preflight_rejects_pending_writes_without_flushing_them() -> None:
    async def run() -> None:
        engine, sessions = await _isolated_db()
        try:
            async with sessions() as session:
                user = User(telegram_id=901004, player_name="Original")
                session.add(user)
                await session.commit()
                user.player_name = "Pending change"
                try:
                    await inspect_account_deletion(session, user_id=user.id, mode="now")
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("A dirty session was accepted")
                await session.rollback()
                await session.refresh(user)
                assert user.player_name == "Original"
        finally:
            await engine.dispose()

    asyncio.run(run())
