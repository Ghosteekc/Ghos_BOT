"""Tests for battle persistence deduplication."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.models.database import Base, BattleCache, User
import bot.models.database as db_module
from bot.services.battle_service import persist_battles
from bot.services.battle_time import battle_time_from_record, battle_times_equal, normalize_battle_time


def _sample_battle(battle_time: str = "20250717T120000.000Z") -> dict:
    return {
        "type": "pvp",
        "battleTime": battle_time,
        "team": [
            {
                "tag": "#ABC123",
                "name": "Player",
                "crowns": 3,
                "cards": [{"name": "Knight"}, {"name": "Archers"}],
            }
        ],
        "opponent": [
            {
                "tag": "#OPP456",
                "name": "Opponent",
                "crowns": 1,
                "cards": [{"name": "Giant"}, {"name": "Musketeer"}],
            }
        ],
    }


async def _run_persist_dedup() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db_module.async_session = session_factory

    async with session_factory() as session:
        user = User(telegram_id=700001, player_tag="#ABC123")
        session.add(user)
        await session.commit()
        await session.refresh(user)

    battle = _sample_battle()
    saved_first = await persist_battles(user, [battle])
    saved_second = await persist_battles(user, [battle])
    saved_variant = await persist_battles(user, [_sample_battle("20250717T120000.000z")])

    async with session_factory() as session:
        rows = (await session.execute(select(BattleCache))).scalars().all()

    assert saved_first == 1
    assert saved_second == 0
    assert saved_variant == 0
    assert len(rows) == 1
    assert rows[0].battle_time == "20250717T120000.000Z"

    await engine.dispose()


async def _run_concurrent_persist() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db_module.async_session = session_factory

    async with session_factory() as session:
        user = User(telegram_id=700002, player_tag="#XYZ999")
        session.add(user)
        await session.commit()
        await session.refresh(user)

    battle = _sample_battle("20250717T130000.000Z")
    results = await asyncio.gather(
        persist_battles(user, [battle]),
        persist_battles(user, [battle]),
        persist_battles(user, [battle]),
    )

    async with session_factory() as session:
        count = len((await session.execute(select(BattleCache))).scalars().all())

    assert sum(results) == 1
    assert count == 1

    await engine.dispose()


def test_normalize_battle_time() -> None:
    assert normalize_battle_time("20250717T120000.000Z") == "20250717T120000.000Z"
    assert normalize_battle_time("20250717T120000.000z") == "20250717T120000.000Z"
    assert normalize_battle_time("") is None
    assert normalize_battle_time(None) is None
    assert battle_times_equal("20250717T120000.000z", "20250717T120000.000Z")
    assert battle_time_from_record({"battleTime": "20250717T120000.000Z"}) == "20250717T120000.000Z"
    assert battle_time_from_record({"warTime": "20250717T140000.000Z"}) == "20250717T140000.000Z"
    assert battle_time_from_record({}) is None


def test_persist_dedup() -> None:
    asyncio.run(_run_persist_dedup())


def test_concurrent_persist() -> None:
    asyncio.run(_run_concurrent_persist())


if __name__ == "__main__":
    test_normalize_battle_time()
    test_persist_dedup()
    test_concurrent_persist()
    print("OK")
