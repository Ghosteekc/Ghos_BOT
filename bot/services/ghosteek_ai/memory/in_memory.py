"""In-memory реализация MemoryProvider."""

from __future__ import annotations

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
