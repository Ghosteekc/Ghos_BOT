"""Tests for persistent aiogram FSM storage used in /link flow."""

from __future__ import annotations

import asyncio

from aiogram.fsm.storage.base import StorageKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import bot.models.database as db_module
from bot.fsm.sqlite_storage import SqliteStorage
from bot.models.database import Base
from bot.states.link import LinkStates


async def _run_storage_survives_restart() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db_module.async_session = session_factory

    key = StorageKey(bot_id=1, chat_id=100, user_id=200)
    storage_a = SqliteStorage()
    await storage_a.set_state(key, LinkStates.waiting_tag)
    await storage_a.set_data(key, {"step": "link"})

    storage_b = SqliteStorage()
    state = await storage_b.get_state(key)
    data = await storage_b.get_data(key)
    assert state == LinkStates.waiting_tag.state
    assert data == {"step": "link"}

    await storage_b.set_state(key, None)
    assert await storage_b.get_state(key) is None

    await engine.dispose()


def test_sqlite_fsm_storage_persists_across_instances() -> None:
    asyncio.run(_run_storage_survives_restart())


if __name__ == "__main__":
    test_sqlite_fsm_storage_persists_across_instances()
    print("OK")
