"""One-time beta tester invite links."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.models.database import Base, BetaInvite, Subscription, User
from bot.services.beta_invite import (
    build_beta_link,
    create_beta_invite,
    parse_beta_payload,
    parse_test_command_days,
    redeem_beta_invite,
)
from bot.services.pro.entitlement import is_user_pro, status_from_subscription


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


def test_parse_test_command_days() -> None:
    assert parse_test_command_days("/test_30") == 30
    assert parse_test_command_days("/test_7@GhosteekBot") == 7
    assert parse_test_command_days("/test_1") == 1
    assert parse_test_command_days("/test_0") is None
    assert parse_test_command_days("/test_9999") is None
    assert parse_test_command_days("/test") is None
    assert parse_test_command_days("/admin_sub") is None


def test_parse_and_build_beta_link() -> None:
    assert parse_beta_payload("beta_abcdef0123456789") == "abcdef0123456789"
    assert parse_beta_payload("beta_XYZ") is None
    assert parse_beta_payload("ref_123") is None
    assert parse_beta_payload(None) is None
    link = build_beta_link(token="abcdef0123456789", bot_username="GhosteekCR")
    assert link == "https://t.me/GhosteekCR?start=beta_abcdef0123456789"


def test_create_and_redeem_once() -> None:
    async def _run() -> None:
        _engine, Session = await _make_db()
        async with Session() as session:
            created = await create_beta_invite(
                session,
                created_by_telegram_id=1,
                days=14,
                bot_username="TestBot",
            )
            token = created.invite.token
            assert "beta_" in created.link
            assert created.invite.days == 14

        async with Session() as session:
            user = await _add_user(session, 42)
            first = await redeem_beta_invite(session, user=user, token=token)
            assert first.ok
            assert first.days == 14
            assert await is_user_pro(session, user)

        async with Session() as session:
            other = await _add_user(session, 99)
            second = await redeem_beta_invite(session, user=other, token=token)
            assert not second.ok
            assert second.reason == "already_used"
            assert not await is_user_pro(session, other)

        async with Session() as session:
            row = (
                await session.execute(select(BetaInvite).where(BetaInvite.token == token))
            ).scalar_one()
            assert row.used_at is not None
            assert row.used_by_telegram_id == 42

            redeemer = (
                await session.execute(select(User).where(User.telegram_id == 42))
            ).scalar_one()
            sub = (
                await session.execute(
                    select(Subscription).where(Subscription.user_id == redeemer.id)
                )
            ).scalar_one()
            status = status_from_subscription(sub)
            assert status.is_pro
            assert status.plan_id == "beta_tester"
            assert status.days_left is not None and status.days_left >= 13

    asyncio.run(_run())


def test_redeem_invalid_token() -> None:
    async def _run() -> None:
        _engine, Session = await _make_db()
        async with Session() as session:
            user = await _add_user(session, 7)
            bad = await redeem_beta_invite(session, user=user, token="deadbeefdeadbeef")
            assert not bad.ok
            assert bad.reason == "not_found"

    asyncio.run(_run())
