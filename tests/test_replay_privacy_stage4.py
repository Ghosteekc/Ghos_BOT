"""Regression checks for closed replay and privacy, using synthetic data."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from bot.api.replay_guard import ReplayAvailabilityMiddleware
from bot.services.ghosteek_ai.context.ai_context import AIContext, PlayerContext
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder
from bot.services.ghosteek_ai.replay import service


def _complete(coroutine):
    with pytest.raises(StopIteration) as finished:
        coroutine.send(None)
    return finished.value.value


@pytest.mark.parametrize("path", [
    "/api/ai/replay/analyze", "/api/ai/replay/analyze/",
    "/api/ai/replay/evidence/other-user-token",
])
def test_closed_replay_rejects_before_auth_or_body(path):
    app = AsyncMock()
    receive = AsyncMock(side_effect=AssertionError("body must not be read"))
    sent = []

    async def send(message):
        sent.append(message)

    _complete(ReplayAvailabilityMiddleware(app)(
        {"type": "http", "path": path, "method": "POST"}, receive, send,
    ))
    assert sent[0]["status"] == 404
    app.assert_not_awaited()
    receive.assert_not_awaited()


def test_other_ai_routes_continue_to_app():
    app = AsyncMock()
    _complete(ReplayAvailabilityMiddleware(app)(
        {"type": "http", "path": "/api/ai/ask"}, AsyncMock(), AsyncMock(),
    ))
    app.assert_awaited_once()


def test_replay_guard_is_installed_on_real_app():
    from bot.api.app import create_app

    assert any(m.cls is ReplayAvailabilityMiddleware for m in create_app().user_middleware)


def test_cancelled_upload_removes_partial_file(monkeypatch):
    from unittest.mock import MagicMock
    from pathlib import Path

    handle = MagicMock(name="fake-file")
    handle.name = "fixture-partial-video.bin"
    unlink = MagicMock()
    monkeypatch.setattr(service.tempfile, "NamedTemporaryFile", lambda **kwargs: handle)
    monkeypatch.setattr(service, "_unlink_quiet", unlink)
    read = AsyncMock(side_effect=[b"fixture-data", asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        service._spool_limited(read).send(None)
    handle.close.assert_called_once()
    unlink.assert_called_once_with(Path("fixture-partial-video.bin"))


def test_prompt_context_does_not_send_player_identifiers():
    ctx = AIContext(player=PlayerContext(telegram_id=12345678, tag="#P0YQ88", name="PrivateFixture"))
    ctx.deck.cards = ["Hog Rider"]
    messages = PromptBuilder().build_ai_context(ctx)
    text = " ".join(message.content for message in messages)
    assert "12345678" not in text
    assert "#P0YQ88" not in text
    assert "PrivateFixture" not in text
    assert "Hog Rider" in text


def test_structured_tool_payload_minimizes_identifiers_without_mutating_facts():
    from bot.services.ghosteek_ai.models import ToolResult

    result = ToolResult(tool="battle_analysis", ok=True, data={
        "telegram_id": 12345678,
        "player_tag": "#P0YQ88",
        "opponent_name": "PrivateFixture",
        "deck": [{"name": "Hog Rider"}],
    })
    for text in (result.to_llm_content(), PromptBuilder._compact_tool_content(result)):
        assert "12345678" not in text
        assert "#P0YQ88" not in text
        assert "PrivateFixture" not in text
        assert "Hog Rider" in text
    assert result.data["telegram_id"] == 12345678


def test_ai_memory_is_isolated_and_expired_session_not_reused():
    from bot.services.ghosteek_ai.conversation.state import SESSION_TTL_SECONDS
    from bot.services.ghosteek_ai.memory.in_memory import InMemoryMemoryProvider
    import time

    provider = InMemoryMemoryProvider()
    alice = provider.get_or_create(101)
    bob = provider.get_or_create(202)
    assert alice is not bob
    alice.updated_at = time.time() - SESSION_TTL_SECONDS - 2
    assert provider.get(101) is None
    assert provider.get(202) is bob
