"""ResponseGenerator поверх LLMProvider (Ollama / Qwen stubs).

Template-режим не затрагивается. Эти генераторы собирают prompt через
PromptBuilder, но не вызывают модель, пока provider не wired.
"""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.messages import ChatMessage
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder
from bot.services.ghosteek_ai.llm.provider import (
    LLMProvider,
    OllamaProvider,
    QwenLLMProvider,
    get_llm_provider,
)
from bot.services.ghosteek_ai.llm.response_parser import ResponseParser


class LLMResponseGenerator:
    """Общий каркас: PromptBuilder → LLMProvider → ResponseParser → text.

    generate() синхронный (как Template), чтобы factory/service не ломались.
    Реальный HTTP — async на стороне provider; до wiring поднимаем
    NotImplementedError после сборки messages.
    """

    backend: str = "llm"

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        prompt_builder: PromptBuilder | None = None,
        response_parser: ResponseParser | None = None,
    ) -> None:
        self.provider = provider or OllamaProvider()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.response_parser = response_parser or ResponseParser()
        self.last_messages: list[ChatMessage] = []

    def build_messages(self, ctx: AIContext) -> list[ChatMessage]:
        self.last_messages = self.prompt_builder.build(ctx)
        return list(self.last_messages)

    def generate(self, ctx: AIContext) -> str:
        messages = self.build_messages(ctx)
        del messages
        raise NotImplementedError(
            f"{type(self).__name__} is not connected yet "
            f"(provider={self.provider.name}). "
            "Use get_response_generator('template') until LLM is wired. "
            "PromptBuilder + LLMProvider interfaces are ready."
        )


class OllamaResponseGenerator(LLMResponseGenerator):
    """Генератор через OllamaProvider (HTTP не подключён)."""

    backend = "ollama"

    def __init__(self, provider: LLMProvider | None = None, **kwargs) -> None:
        super().__init__(provider or OllamaProvider(), **kwargs)


class QwenResponseGenerator(LLMResponseGenerator):
    """Генератор через QwenLLMProvider (клиент не подключён)."""

    backend = "qwen"

    def __init__(self, provider: LLMProvider | None = None, **kwargs) -> None:
        super().__init__(provider or QwenLLMProvider(), **kwargs)


# Alias по ТЗ / factory
OllamaGenerator = OllamaResponseGenerator
QwenGenerator = QwenResponseGenerator


def make_llm_response_generator(backend: str) -> LLMResponseGenerator:
    key = (backend or "").strip().lower()
    if key in {"qwen", "dashscope"}:
        return QwenResponseGenerator()
    if key in {"ollama", "local"}:
        return OllamaResponseGenerator()
    return LLMResponseGenerator(get_llm_provider(key))
