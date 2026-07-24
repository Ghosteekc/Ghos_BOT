"""Route-level tests for GET/PUT /api/settings (persistent storage)."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.api.routes.misc import get_settings, update_settings
from bot.api.schemas import SettingsUpdateRequest
from bot.models.database import Base, User, UserSettings


async def _session_with_user(telegram_id: int) -> tuple[AsyncSession, User]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = session_factory()
    user = User(telegram_id=telegram_id)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return session, user


async def _run_get_creates_defaults() -> None:
    session, user = await _session_with_user(910_001)
    try:
        before = await session.execute(select(UserSettings).where(UserSettings.user_id == user.id))
        assert before.scalar_one_or_none() is None

        body = await get_settings(user=user, session=session)
        assert body.theme == "dark"
        assert body.haptic_enabled is True

        after = await session.execute(select(UserSettings).where(UserSettings.user_id == user.id))
        assert after.scalar_one_or_none() is not None
    finally:
        await session.close()


async def _run_put_then_get_roundtrip() -> None:
    session, user = await _session_with_user(910_002)
    try:
        await get_settings(user=user, session=session)

        saved = await update_settings(
            payload=SettingsUpdateRequest(haptic_enabled=False, theme="light"),
            user=user,
            session=session,
        )
        assert saved.haptic_enabled is False
        assert saved.theme == "light"
        assert saved.telegram_notifications is True

        reloaded = await get_settings(user=user, session=session)
        assert reloaded.haptic_enabled is False
        assert reloaded.theme == "light"
        assert reloaded.notifications is True
    finally:
        await session.close()


async def _run_partial_put_preserves_fields() -> None:
    session, user = await _session_with_user(910_003)
    try:
        await update_settings(
            payload=SettingsUpdateRequest(theme="auto", notifications=False),
            user=user,
            session=session,
        )
        patched = await update_settings(
            payload=SettingsUpdateRequest(haptic_enabled=False),
            user=user,
            session=session,
        )
        assert patched.theme == "auto"
        assert patched.notifications is False
        assert patched.haptic_enabled is False
    finally:
        await session.close()


def test_settings_get_creates_row_with_defaults() -> None:
    asyncio.run(_run_get_creates_defaults())


def test_settings_put_persists_and_get_returns_saved() -> None:
    asyncio.run(_run_put_then_get_roundtrip())


def test_settings_partial_put_does_not_reset_other_fields() -> None:
    asyncio.run(_run_partial_put_preserves_fields())


if __name__ == "__main__":
    test_settings_get_creates_row_with_defaults()
    test_settings_put_persists_and_get_returns_saved()
    test_settings_partial_put_does_not_reset_other_fields()
    print("OK")
