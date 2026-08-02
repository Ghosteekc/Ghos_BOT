"""Memory package — MemoryProvider + summary compression."""

from bot.services.ghosteek_ai.memory.in_memory import InMemoryMemoryProvider
from bot.services.ghosteek_ai.memory.provider import (
    MemoryProvider,
    get_memory_provider,
    set_memory_provider,
)
from bot.services.ghosteek_ai.memory.summary import maybe_compress, summarize_messages

__all__ = [
    "InMemoryMemoryProvider",
    "MemoryProvider",
    "get_memory_provider",
    "set_memory_provider",
    "maybe_compress",
    "summarize_messages",
]
