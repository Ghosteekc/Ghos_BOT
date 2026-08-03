"""ResponseGenerator — интерфейс для Template / Ollama / Qwen.

Factory выбирает backend по конфигу (GHOSTEEK_AI_BACKEND).
TemplateGenerator остаётся fallback при ошибках LLM.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from bot.services.ghosteek_ai.context.ai_context import AIContext


@runtime_checkable
class ResponseGenerator(Protocol):
    """Контракт генератора ответа игроку из AIContext."""

    def generate(self, ctx: AIContext) -> str:
        """AIContext → текст ответа (без вызова доменных сервисов)."""
        ...


# Имена бэкендов для factory (без подключения модели)
GENERATOR_TEMPLATE = "template"
GENERATOR_OLLAMA = "ollama"
GENERATOR_QWEN = "qwen"
DEFAULT_GENERATOR = GENERATOR_TEMPLATE
