"""In-memory реализация MemoryProvider."""

from __future__ import annotations

import asyncio
import time

from bot.services.ghosteek_ai.conversation.state import ConversationState


class InMemoryMemoryProvider:
    """Process-local dict. Заменяется на Redis без смены менеджера."""

    def __init__(self) -> None:
        self._sessions: dict[int, ConversationState] = {}

    def get(self, telegram_id: int) -> ConversationState | None:
        session = self._sessions.get(telegram_id)
        if session is None:
            return None
        if session.expired():
            self._sessions.pop(telegram_id, None)
            return None
        return session

    def get_or_create(self, telegram_id: int) -> ConversationState:
        session = self.get(telegram_id)
        if session is None:
            session = ConversationState()
            self._sessions[telegram_id] = session
        session.touch()
        return session

    def save(self, telegram_id: int, state: ConversationState) -> None:
        state.touch()
        self._sessions[telegram_id] = state

    def clear(self, telegram_id: int) -> None:
        self._sessions.pop(telegram_id, None)

    def clear_all(self) -> None:
        self._sessions.clear()

    def prune_expired(self, *, now: float | None = None) -> int:
        """Release idle sessions without waiting for another user request."""
        current = time.time() if now is None else now
        expired_ids = [
            telegram_id
            for telegram_id, session in self._sessions.items()
            if session.expired(now=current)
        ]
        for telegram_id in expired_ids:
            self._sessions.pop(telegram_id, None)
        return len(expired_ids)


async def run_periodic_cleanup(
    provider: InMemoryMemoryProvider,
    stop_event: asyncio.Event,
    *,
    interval_seconds: float = 60,
) -> None:
    """Run one process-local sweep loop that stops with the application."""
    while not stop_event.is_set():
        provider.prune_expired()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
