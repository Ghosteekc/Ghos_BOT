"""Tests for one CR account per Telegram user linking rules."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.models.database import Base, User
from bot.services.clash_api import PlayerTagAlreadyLinkedError, SubscriptionService


def _player_data(name: str = "TestPlayer") -> dict:
    return {
        "name": name,
        "trophies": 5000,
        "arena": {"id": 54000016, "name": "Arena 16"},
    }


async def _run_link_scenarios() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        service = SubscriptionService(session)
        user1 = await service.get_or_create_user(800001)
        user2 = await service.get_or_create_user(800002)

    async with session_factory() as session:
        service = SubscriptionService(session)
        user1 = await session.get(User, user1.id)
        linked = await service.link_player(user1, "#ABC123", _player_data("Alpha"))
        assert linked.player_tag == "#ABC123"

    async with session_factory() as session:
        service = SubscriptionService(session)
        user1 = await session.get(User, user1.id)
        refreshed = await service.link_player(user1, "#ABC123", _player_data("Alpha Updated"))
        assert refreshed.player_tag == "#ABC123"
        assert refreshed.player_name == "Alpha Updated"

    async with session_factory() as session:
        service = SubscriptionService(session)
        user2 = await session.get(User, user2.id)
        try:
            await service.link_player(user2, "#ABC123", _player_data("Beta"))
            raise AssertionError("expected PlayerTagAlreadyLinkedError")
        except PlayerTagAlreadyLinkedError as exc:
            assert exc.player_tag == "#ABC123"

    async with session_factory() as session:
        service = SubscriptionService(session)
        user2 = await session.get(User, user2.id)
        linked2 = await service.link_player(user2, "#XYZ999", _player_data("Beta"))
        assert linked2.player_tag == "#XYZ999"

    # Rebind same Telegram user to another free tag — session cache for old tag must drop.
    from bot.services.battle_session_cache import get_session_battles, set_session_battles

    set_session_battles(800001, "#ABC123", [{"id": "old-log"}])
    async with session_factory() as session:
        service = SubscriptionService(session)
        user1 = await session.get(User, user1.id)
        retagged = await service.link_player(user1, "#NEW777", _player_data("Gamma"))
        assert retagged.player_tag == "#NEW777"
    assert get_session_battles(800001, expected_tag="#ABC123") is None
    assert get_session_battles(800001, expected_tag="#NEW777") is None

    await engine.dispose()


def test_player_tag_link_scenarios() -> None:
    asyncio.run(_run_link_scenarios())


if __name__ == "__main__":
    test_player_tag_link_scenarios()
    print("OK")
