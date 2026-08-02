"""MemoryProvider — абстракция хранилища диалоговой памяти.

Сейчас: InMemoryMemoryProvider.
Позже: RedisMemoryProvider без смены Conversation Manager.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from bot.services.ghosteek_ai.conversation.state import ConversationState


@runtime_checkable
class MemoryProvider(Protocol):
    """Интерфейс памяти сессий Ghosteek AI."""

    def get(self, telegram_id: int) -> ConversationState | None:
        """Вернуть сессию или None (нет / протухла)."""
        ...

    def get_or_create(self, telegram_id: int) -> ConversationState:
        """Получить или создать сессию; обновить TTL touch."""
        ...

    def save(self, telegram_id: int, state: ConversationState) -> None:
        """Персистить состояние (для InMemory — no-op поверх dict)."""
        ...

    def clear(self, telegram_id: int) -> None:
        ...

    def clear_all(self) -> None:
        ...


_provider: MemoryProvider | None = None


def get_memory_provider() -> MemoryProvider:
    global _provider
    if _provider is None:
        from bot.services.ghosteek_ai.memory.in_memory import InMemoryMemoryProvider

        _provider = InMemoryMemoryProvider()
    return _provider


def set_memory_provider(provider: MemoryProvider) -> None:
    """Подменить провайдер (тесты / Redis)."""
    global _provider
    _provider = provider
