"""Tests for persisted user settings."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.api.schemas import SettingsUpdateRequest
from bot.models.database import Base, User, UserSettings
from bot.services.user_settings import load_settings_response, update_user_settings


async def _run_persist_roundtrip() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        user = User(telegram_id=900001)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    async with session_factory() as session:
        defaults = await load_settings_response(session, user_id)
        assert defaults.theme == "dark"
        assert defaults.notifications is True
        assert defaults.haptic_enabled is True

    async with session_factory() as session:
        updated = await update_user_settings(
            session,
            user_id,
            SettingsUpdateRequest(haptic_enabled=False),
        )
        assert updated.haptic_enabled is False

    async with session_factory() as session:
        reloaded = await load_settings_response(session, user_id)
        assert reloaded.haptic_enabled is False

    async with session_factory() as session:
        updated = await update_user_settings(
            session,
            user_id,
            SettingsUpdateRequest(theme="light", notifications=False),
        )
        assert updated.theme == "light"
        assert updated.notifications is False
        assert updated.telegram_notifications is True

    async with session_factory() as session:
        reloaded = await load_settings_response(session, user_id)
        assert reloaded.theme == "light"
        assert reloaded.notifications is False

    async with session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
        row = result.scalar_one()
        assert row.theme == "light"
        assert row.notifications is False

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _run_user_isolation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        u1 = User(telegram_id=900002)
        u2 = User(telegram_id=900003)
        session.add_all([u1, u2])
        await session.commit()
        await session.refresh(u1)
        await session.refresh(u2)

    async with session_factory() as session:
        await update_user_settings(session, u1.id, SettingsUpdateRequest(theme="auto"))

    async with session_factory() as session:
        s1 = await load_settings_response(session, u1.id)
        s2 = await load_settings_response(session, u2.id)
        assert s1.theme == "auto"
        assert s2.theme == "dark"

    await engine.dispose()


def test_settings_persist_roundtrip() -> None:
    asyncio.run(_run_persist_roundtrip())


def test_settings_user_isolation() -> None:
    asyncio.run(_run_user_isolation())


if __name__ == "__main__":
    test_settings_persist_roundtrip()
    test_settings_user_isolation()
    print("OK")
