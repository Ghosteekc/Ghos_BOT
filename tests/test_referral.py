"""Referral Credits v2: attribution, ledger, 50% cap, first-purchase rewards."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.models.database import Base, CreditTransaction, ProPayment, Referral, Subscription, User
from bot.services.credits import (
    TYPE_REFERRAL_FRIEND_REWARD,
    TYPE_REFERRAL_REWARD,
    TYPE_SUBSCRIPTION_DISCOUNT,
    credit_once,
    get_credits_balance,
    spend_credits_once,
)
from bot.services.pro.activation import activate_pro_from_payload
from bot.services.pro.entitlement import is_user_pro
from bot.services.pro.plans import PRO_PLANS, get_plan_stars, parse_invoice_payload
from bot.services.pro.pricing import (
    apply_percent_discount,
    build_purchase_quote,
    max_credits_for_price,
)
from bot.services.referral.service import (
    build_referral_link,
    get_invitee_discount,
    grant_referral_purchase_credits,
    parse_referral_payload,
    process_referral_conversion,
    quote_plan_purchase,
    referral_stats_for_user,
)


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
    link = build_referral_link(telegram_id=42, bot_username="GhosteekCR")
    assert link == "https://t.me/GhosteekCR?start=ref_42"


def test_pricing_cap_examples() -> None:
    q = build_purchase_quote(
        plan_id="pro_1m", base_price=100, referral_discount=False, available_credits=10
    )
    assert q is not None
    assert q.stars_to_pay == 90
    assert q.credits_to_use == 10

    q2 = build_purchase_quote(
        plan_id="pro_1m", base_price=100, referral_discount=False, available_credits=80
    )
    assert q2 is not None
    assert q2.max_credits == 50
    assert q2.credits_to_use == 50
    assert q2.stars_to_pay == 50

    q3 = build_purchase_quote(
        plan_id="pro_3m", base_price=250, referral_discount=False, available_credits=500
    )
    assert q3 is not None
    assert q3.stars_to_pay == 125
    assert q3.credits_to_use == 125

    q4 = build_purchase_quote(
        plan_id="pro_6m", base_price=500, referral_discount=False, available_credits=1000
    )
    assert q4 is not None
    assert q4.stars_to_pay == 250
    assert q4.credits_to_use == 250
    assert q4.stars_to_pay >= 1


def test_discount_then_credits_rounding() -> None:
    cut, final = apply_percent_discount(100, 15)
    assert cut == 15
    assert final == 85
    assert max_credits_for_price(85) == 42
    q = build_purchase_quote(
        plan_id="pro_1m",
        base_price=100,
        referral_discount=True,
        available_credits=100,
        discount_percent=15,
    )
    assert q is not None
    assert q.final_price == 85
    assert q.max_credits == 42
    assert q.credits_to_use == 42
    assert q.stars_to_pay == 43
    assert q.stars_to_pay >= 1


def test_never_zero_stars() -> None:
    for price in (1, 2, 3, 85, 100, 500):
        q = build_purchase_quote(
            plan_id="pro_1m",
            base_price=price,
            referral_discount=False,
            available_credits=10_000,
        )
        assert q is not None
        assert q.stars_to_pay >= 1
        assert q.credits_to_use + q.stars_to_pay == q.final_price


def test_payload_credits_roundtrip() -> None:
    from bot.services.pro.plans import build_invoice_payload

    payload = build_invoice_payload(
        plan_id="pro_1m", telegram_id=7, nonce="abc", credits_used=42
    )
    parsed = parse_invoice_payload(payload)
    assert parsed == ("pro_1m", 7, 42)
    legacy = parse_invoice_payload("ghosteek_pro:pro_1m:7:nonceonly")
    assert legacy == ("pro_1m", 7, 0)


async def _run_referral_attribution() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 200_001)
        new_user = await _add_user(session, 200_002)
        existing = await _add_user(session, 200_003)

        ok = await process_referral_conversion(
            session,
            referred_user=new_user,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=True,
        )
        assert ok.accepted is True
        assert await get_credits_balance(session, referrer.id) == 0

        deny_existing = await process_referral_conversion(
            session,
            referred_user=existing,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=False,
        )
        assert deny_existing.reason == "existing_user"

        deny_self = await process_referral_conversion(
            session,
            referred_user=referrer,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=True,
        )
        assert deny_self.reason == "self_referral"

        again = await process_referral_conversion(
            session,
            referred_user=new_user,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=True,
        )
        assert again.reason == "already_referred"

        other = await _add_user(session, 200_004)
        await process_referral_conversion(
            session,
            referred_user=new_user,
            referrer_telegram_id=other.telegram_id,
            is_new_user=True,
        )
        row = (
            await session.execute(select(Referral).where(Referral.referred_user_id == new_user.id))
        ).scalar_one()
        assert row.referrer_user_id == referrer.id
    await engine.dispose()


def test_referral_attribution_rules() -> None:
    asyncio.run(_run_referral_attribution())


async def _run_first_purchase_credits() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        referrer = await _add_user(session, 201_001)
        invitee = await _add_user(session, 201_002)
        await process_referral_conversion(
            session,
            referred_user=invitee,
            referrer_telegram_id=referrer.telegram_id,
            is_new_user=True,
        )
        disc = await get_invitee_discount(session, invitee)
        assert disc.active is True
        assert disc.percent == 15

        plan = PRO_PLANS["pro_1m"]
        first = await activate_pro_from_payload(
            session,
            invitee,
            plan_id=plan.id,
            payment_charge_id="charge-ref-1",
            amount_stars=85,
            credits_used=0,
            invoice_payload=f"ghosteek_pro:{plan.id}:{invitee.telegram_id}:n:0",
        )
        assert first.activated is True
        assert await get_credits_balance(session, referrer.id) == 10
        assert await get_credits_balance(session, invitee.id) == 10

        # Duplicate callback
        dup = await activate_pro_from_payload(
            session,
            invitee,
            plan_id=plan.id,
            payment_charge_id="charge-ref-1",
            amount_stars=85,
            credits_used=0,
        )
        assert dup.duplicate is True
        assert await get_credits_balance(session, referrer.id) == 10

        # Second purchase — no extra referral credits
        second = await activate_pro_from_payload(
            session,
            invitee,
            plan_id=plan.id,
            payment_charge_id="charge-ref-2",
            amount_stars=100,
            credits_used=0,
        )
        assert second.activated is True
        assert await get_credits_balance(session, referrer.id) == 10

        disc2 = await get_invitee_discount(session, invitee)
        assert disc2.active is False

        stats = await referral_stats_for_user(session, referrer)
        assert stats.friends_purchased == 1
        assert stats.credits_earned_from_referrals == 10
    await engine.dispose()


def test_first_purchase_grants_credits_once() -> None:
    asyncio.run(_run_first_purchase_credits())


async def _run_chain_abc() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        a = await _add_user(session, 202_001)
        b = await _add_user(session, 202_002)
        c = await _add_user(session, 202_003)
        await process_referral_conversion(
            session, referred_user=b, referrer_telegram_id=a.telegram_id, is_new_user=True
        )
        await process_referral_conversion(
            session, referred_user=c, referrer_telegram_id=b.telegram_id, is_new_user=True
        )
        await activate_pro_from_payload(
            session,
            c,
            plan_id="pro_1m",
            payment_charge_id="charge-c-1",
            amount_stars=85,
        )
        assert await get_credits_balance(session, a.id) == 0
        assert await get_credits_balance(session, b.id) == 10
        assert await get_credits_balance(session, c.id) == 10
    await engine.dispose()


def test_direct_referrer_only_abc() -> None:
    asyncio.run(_run_chain_abc())


async def _run_credits_spend_on_purchase() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 203_001)
        await credit_once(
            session,
            user_id=user.id,
            amount=80,
            tx_type=TYPE_REFERRAL_REWARD,
            reference_id="seed-80",
        )
        await session.commit()
        quote = await quote_plan_purchase(session, user, "pro_1m")
        assert quote is not None
        assert quote.credits_to_use == 50
        assert quote.stars_to_pay == 50

        result = await activate_pro_from_payload(
            session,
            user,
            plan_id="pro_1m",
            payment_charge_id="charge-cred-1",
            amount_stars=50,
            credits_used=50,
        )
        assert result.activated is True
        assert await get_credits_balance(session, user.id) == 30
        assert await is_user_pro(session, user) is True

        # Failed spend path: balance unchanged if we never activate
        bal = await get_credits_balance(session, user.id)
        assert bal == 30
    await engine.dispose()


def test_credits_spent_only_after_successful_payment() -> None:
    asyncio.run(_run_credits_spend_on_purchase())


async def _run_ledger_no_negative() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 204_001)
        await credit_once(
            session,
            user_id=user.id,
            amount=5,
            tx_type=TYPE_REFERRAL_REWARD,
            reference_id="seed-5",
        )
        await session.commit()
        try:
            await spend_credits_once(
                session, user_id=user.id, amount=10, reference_id="spend-too-much"
            )
            raise AssertionError("expected insufficient_credits")
        except ValueError as exc:
            assert "insufficient" in str(exc)
        assert await get_credits_balance(session, user.id) == 5

        # Idempotent spend
        await spend_credits_once(session, user_id=user.id, amount=5, reference_id="spend-5")
        await session.commit()
        await spend_credits_once(session, user_id=user.id, amount=5, reference_id="spend-5")
        assert await get_credits_balance(session, user.id) == 0
    await engine.dispose()


def test_ledger_balance_and_no_negative() -> None:
    asyncio.run(_run_ledger_no_negative())


async def _run_stars_without_credits() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 205_001)
        result = await activate_pro_from_payload(
            session,
            user,
            plan_id="pro_1m",
            payment_charge_id="charge-plain-1",
            amount_stars=100,
            credits_used=0,
        )
        assert result.activated is True
        assert await is_user_pro(session, user) is True
        assert await get_credits_balance(session, user.id) == 0
    await engine.dispose()


def test_existing_stars_purchase_without_credits() -> None:
    asyncio.run(_run_stars_without_credits())


def test_catalog_discount_percent() -> None:
    assert get_plan_stars("pro_1m") == 100
    assert get_plan_stars("pro_1m", referral_discount=True) == 85
    assert get_plan_stars("pro_3m", referral_discount=True) == 213  # 250 - floor(37.5)=250-37
    assert get_plan_stars("pro_6m", referral_discount=True) == 425
