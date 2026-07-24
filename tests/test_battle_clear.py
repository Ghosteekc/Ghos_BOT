"""Tests for scoped battle history deletion."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import bot.models.database as db_module
from bot.api.routes.battles import clear_battle_history
from bot.models.database import Base, BattleCache, User
from bot.services.battle_service import delete_persisted_battles_for_user


def _battle_row(tag: str, battle_time: str) -> BattleCache:
    return BattleCache(
        player_tag=tag,
        battle_time=battle_time,
        result="win",
        user_deck="Knight,Archers",
        opponent_deck="Giant,Musketeer",
    )


async def _run_user_isolation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db_module.async_session = session_factory

    async with session_factory() as session:
        user_a = User(telegram_id=920_001, player_tag="#AAA111")
        user_b = User(telegram_id=920_002, player_tag="#BBB222")
        session.add_all(
            [
                user_a,
                user_b,
                _battle_row("#AAA111", "20250701T120000.000Z"),
                _battle_row("#AAA111", "20250702T120000.000Z"),
                _battle_row("#BBB222", "20250703T120000.000Z"),
            ]
        )
        await session.commit()
        await session.refresh(user_a)
        await session.refresh(user_b)

    deleted = await delete_persisted_battles_for_user(user_a)
    assert deleted == 2

    async with session_factory() as session:
        remaining_b = (
            await session.execute(select(BattleCache).where(BattleCache.player_tag == "#BBB222"))
        ).scalars().all()
        assert len(remaining_b) == 1

    response = await clear_battle_history(user=user_b)
    assert response.deleted_count == 1

    async with session_factory() as session:
        rows = (await session.execute(select(BattleCache))).scalars().all()
        assert len(rows) == 0

    await engine.dispose()


async def _run_no_tag_no_delete() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db_module.async_session = session_factory

    async with session_factory() as session:
        user = User(telegram_id=920_003)
        session.add(user)
        session.add(_battle_row("#ZZZ999", "20250704T120000.000Z"))
        await session.commit()
        await session.refresh(user)

    deleted = await delete_persisted_battles_for_user(user)
    assert deleted == 0

    async with session_factory() as session:
        count = len((await session.execute(select(BattleCache))).scalars().all())
    assert count == 1

    await engine.dispose()


def test_delete_battles_only_for_linked_tag() -> None:
    asyncio.run(_run_user_isolation())


def test_user_without_tag_cannot_delete_rows() -> None:
    asyncio.run(_run_no_tag_no_delete())


if __name__ == "__main__":
    test_delete_battles_only_for_linked_tag()
    test_user_without_tag_cannot_delete_rows()
    print("OK")
