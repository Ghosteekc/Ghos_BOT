"""Bootstrap after link warms battles for Mini App first open."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.services.user_bootstrap import bootstrap_linked_user


def test_bootstrap_linked_user_persists_session_and_counts() -> None:
    user = SimpleNamespace(
        id=1,
        telegram_id=900001,
        player_tag="#ABC123",
        player_name="Tester",
        arena_id=1,
        trophies=5000,
    )
    battles = [{"battleTime": "20260101T000000.000Z", "type": "PvP"}]

    async def _run() -> None:
        with (
            patch(
                "bot.services.user_bootstrap.load_and_persist",
                new=AsyncMock(return_value=battles),
            ),
            patch("bot.services.user_bootstrap.set_session_battles") as set_session,
            patch(
                "bot.services.user_bootstrap._profile_current_deck",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "bot.services.mine_decks.sync_tracked_mine_decks",
                new=AsyncMock(return_value=[{"cards": ["a"] * 8}]),
            ),
        ):
            out = await bootstrap_linked_user(user, force=True)
            assert out["ok"] is True
            assert out["battles_loaded"] == 1
            assert out["mine_decks"] == 1
            set_session.assert_called_once()

    asyncio.run(_run())


def test_bootstrap_without_tag() -> None:
    user = SimpleNamespace(
        id=1,
        telegram_id=900002,
        player_tag=None,
        player_name=None,
        arena_id=None,
        trophies=None,
    )

    async def _run() -> None:
        out = await bootstrap_linked_user(user)
        assert out["ok"] is False
        assert out["battles_loaded"] == 0

    asyncio.run(_run())
