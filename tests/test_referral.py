"""Referral system: conversions, rewards, API progress."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.models.database import Base, Referral, ReferralReward, Subscription, User
from bot.services.pro.activation import activate_pro_from_payload, extend_pro_days
from bot.services.pro.entitlement import is_user_pro
from bot.services.pro.plans import PRO_PLANS
from bot.services.referral.service import (
    REQUIRED_REFERRALS,
    REWARD_DAYS,
    build_referral_link,
    parse_referral_payload,
    process_referral_conversion,
    referral_stats_for_user,
)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _make_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _add_user(session: AsyncSession, telegram_id: int) -> User:
    user = User(telegram_id=telegram_id)
    session.add(user)
    await session.flush()
    session.add(Subscription(user_id=user.id, is_active=False, expires_at=None))
    await session.commit()
    await session.refresh(user)
    return user


def test_parse_and_build_referral_link() -> None:
    assert parse_referral_payload("ref_12345") == 12345
    assert parse_referral_payload("ref_abc") is None
    assert parse_referral_payload(None) is None
    assert parse_referral_payload("start") is None
    link = build_referral_link(telegram_id=42, bot_username="GhosteekCR")
    assert link == "https://t.me/GhosteekCR?start=ref_42"


async def _run_new_user_with_referral_counts() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_001)
        referred = await _add_user(session, 100_002)
        result = await process_referral_conversion(
            session,
            referred_user=referred,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=True,
        )
        assert result.accepted is True
        assert result.rewards_granted == 0
        stats = await referral_stats_for_user(session, referrer, bot_username="bot")
        assert stats.successful_referrals == 1
        assert stats.current_progress == 1
        assert stats.next_reward_in == 4
    await engine.dispose()


def test_new_user_referral_counts() -> None:
    asyncio.run(_run_new_user_with_referral_counts())


async def _run_no_referral_without_payload() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_011)
        referred = await _add_user(session, 100_012)
        result = await process_referral_conversion(
            session,
            referred_user=referred,
            referrer_telegram_id=None,
            is_new_user=True,
        )
        assert result.accepted is False
        assert result.reason == "no_payload"
        stats = await referral_stats_for_user(session, referrer)
        assert stats.successful_referrals == 0
    await engine.dispose()


def test_no_referral_without_payload() -> None:
    asyncio.run(_run_no_referral_without_payload())


async def _run_self_referral_rejected() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 100_021)
        result = await process_referral_conversion(
            session,
            referred_user=user,
            referrer_telegram_id=user.telegram_id,
            is_new_user=True,
        )
        assert result.accepted is False
        assert result.reason == "self_referral"
    await engine.dispose()


def test_self_referral_rejected() -> None:
    asyncio.run(_run_self_referral_rejected())


async def _run_existing_user_not_counted() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_031)
        referred = await _add_user(session, 100_032)
        result = await process_referral_conversion(
            session,
            referred_user=referred,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=False,
        )
        assert result.accepted is False
        assert result.reason == "existing_user"
        assert (await referral_stats_for_user(session, referrer)).successful_referrals == 0
    await engine.dispose()


def test_existing_user_not_counted() -> None:
    asyncio.run(_run_existing_user_not_counted())


async def _run_repeat_start_no_second_referral() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_041)
        referred = await _add_user(session, 100_042)
        first = await process_referral_conversion(
            session,
            referred_user=referred,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=True,
        )
        assert first.accepted is True
        second = await process_referral_conversion(
            session,
            referred_user=referred,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=True,
        )
        assert second.accepted is False
        assert second.reason == "already_referred"
        assert (await referral_stats_for_user(session, referrer)).successful_referrals == 1
    await engine.dispose()


def test_repeat_start_no_second_referral() -> None:
    asyncio.run(_run_repeat_start_no_second_referral())


async def _run_one_referrer_only() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        a = await _add_user(session, 100_051)
        b = await _add_user(session, 100_052)
        referred = await _add_user(session, 100_053)
        first = await process_referral_conversion(
            session,
            referred_user=referred,
            referrer_telegram_id=a.telegram_id,
            is_new_user=True,
        )
        assert first.accepted is True
        second = await process_referral_conversion(
            session,
            referred_user=referred,
            referrer_telegram_id=b.telegram_id,
            is_new_user=True,
        )
        assert second.accepted is False
        assert (await referral_stats_for_user(session, a)).successful_referrals == 1
        assert (await referral_stats_for_user(session, b)).successful_referrals == 0
    await engine.dispose()


def test_one_referred_has_single_referrer() -> None:
    asyncio.run(_run_one_referrer_only())


async def _invite_n(session: AsyncSession, referrer: User, n: int, base_tg: int) -> int:
    rewards = 0
    for i in range(n):
        referred = await _add_user(session, base_tg + i)
        result = await process_referral_conversion(
            session,
            referred_user=referred,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=True,
        )
        assert result.accepted is True
        rewards += result.rewards_granted
    return rewards


async def _run_four_no_reward() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_061)
        granted = await _invite_n(session, referrer, 4, 200_000)
        assert granted == 0
        stats = await referral_stats_for_user(session, referrer)
        assert stats.current_progress == 4
        assert stats.rewards_earned == 0
        assert await is_user_pro(session, referrer) is False
    await engine.dispose()


def test_four_referrals_no_reward() -> None:
    asyncio.run(_run_four_no_reward())


async def _run_five_grants_twenty_days() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_071)
        before = _utc_now()
        granted = await _invite_n(session, referrer, 5, 201_000)
        assert granted == 1
        assert await is_user_pro(session, referrer) is True
        stats = await referral_stats_for_user(session, referrer)
        assert stats.rewards_earned == 1
        assert stats.current_progress == 0
        assert stats.successful_referrals == 5
        sub = (
            await session.execute(select(Subscription).where(Subscription.user_id == referrer.id))
        ).scalar_one()
        assert sub.expires_at is not None
        expected = before + timedelta(days=REWARD_DAYS)
        assert abs((_aware(sub.expires_at) - expected).total_seconds()) < 120
    await engine.dispose()


def test_five_referrals_grant_twenty_days() -> None:
    asyncio.run(_run_five_grants_twenty_days())


async def _run_ten_grants_forty_days() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_081)
        before = _utc_now()
        granted = await _invite_n(session, referrer, 10, 202_000)
        assert granted == 2
        stats = await referral_stats_for_user(session, referrer)
        assert stats.rewards_earned == 2
        assert stats.days_earned_total == 40
        assert stats.current_progress == 0
        sub = (
            await session.execute(select(Subscription).where(Subscription.user_id == referrer.id))
        ).scalar_one()
        expected = before + timedelta(days=40)
        assert abs((_aware(sub.expires_at) - expected).total_seconds()) < 120
    await engine.dispose()


def test_ten_referrals_grant_forty_days() -> None:
    asyncio.run(_run_ten_grants_forty_days())


async def _run_extends_active_pro() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_091)
        base_exp = _utc_now() + timedelta(days=10)
        sub = (
            await session.execute(select(Subscription).where(Subscription.user_id == referrer.id))
        ).scalar_one()
        sub.is_active = True
        sub.started_at = _utc_now()
        sub.expires_at = base_exp
        sub.plan_id = "pro_1m"
        await session.commit()

        await _invite_n(session, referrer, 5, 203_000)
        sub = (
            await session.execute(select(Subscription).where(Subscription.user_id == referrer.id))
        ).scalar_one()
        expected = base_exp + timedelta(days=REWARD_DAYS)
        assert abs((_aware(sub.expires_at) - expected).total_seconds()) < 120
    await engine.dispose()


def test_referral_extends_active_pro() -> None:
    asyncio.run(_run_extends_active_pro())


async def _run_creates_pro_when_absent() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_101)
        await _invite_n(session, referrer, 5, 204_000)
        assert await is_user_pro(session, referrer) is True
    await engine.dispose()


def test_referral_creates_pro_when_absent() -> None:
    asyncio.run(_run_creates_pro_when_absent())


async def _run_reward_not_duplicated() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_111)
        await _invite_n(session, referrer, 5, 205_000)
        # Force grant again — should be no-op (no unconsumed).
        from bot.services.referral.service import _grant_pending_rewards

        again = await _grant_pending_rewards(session, referrer)
        await session.commit()
        assert again == 0
        rewards = (
            await session.execute(
                select(ReferralReward).where(ReferralReward.referrer_user_id == referrer.id)
            )
        ).scalars().all()
        assert len(rewards) == 1
    await engine.dispose()


def test_reward_not_duplicated() -> None:
    asyncio.run(_run_reward_not_duplicated())


async def _run_api_stats_shape() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_121)
        await _invite_n(session, referrer, 3, 206_000)
        stats = await referral_stats_for_user(session, referrer, bot_username="GhosteekCR")
        assert stats.referral_link.startswith("https://t.me/GhosteekCR?start=ref_")
        assert stats.successful_referrals == 3
        assert stats.current_progress == 3
        assert stats.required_referrals == REQUIRED_REFERRALS
        assert stats.reward_days == REWARD_DAYS
        assert stats.next_reward_in == 2
        assert stats.rewards_earned == 0
    await engine.dispose()


def test_referral_api_stats() -> None:
    asyncio.run(_run_api_stats_shape())


async def _run_stars_purchase_still_works() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 100_131)
        plan = PRO_PLANS["pro_1m"]
        result = await activate_pro_from_payload(
            session,
            user,
            plan_id=plan.id,
            payment_charge_id="charge-ref-stars-1",
            invoice_payload=f"ghosteek_pro:{plan.id}:{user.telegram_id}:abc",
        )
        assert result.activated is True
        assert await is_user_pro(session, user) is True
    await engine.dispose()


def test_stars_purchase_still_works() -> None:
    asyncio.run(_run_stars_purchase_still_works())


async def _run_is_pro_sees_referral_pro() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_141)
        await extend_pro_days(session, referrer, days=REWARD_DAYS, plan_id="referral_20d")
        assert await is_user_pro(session, referrer) is True
    await engine.dispose()


def test_is_pro_sees_referral_earned_pro() -> None:
    asyncio.run(_run_is_pro_sees_referral_pro())


async def _run_nine_progress() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 100_151)
        await _invite_n(session, referrer, 9, 207_000)
        stats = await referral_stats_for_user(session, referrer)
        assert stats.successful_referrals == 9
        assert stats.rewards_earned == 1
        assert stats.current_progress == 4
        assert stats.next_reward_in == 1
    await engine.dispose()


def test_nine_referrals_progress() -> None:
    asyncio.run(_run_nine_progress())
