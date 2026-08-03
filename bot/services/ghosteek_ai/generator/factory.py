"""Factory ResponseGenerator — template / ollama / qwen (default = template)."""

from __future__ import annotations

from bot.services.ghosteek_ai.generator.base import (
    DEFAULT_GENERATOR,
    GENERATOR_OLLAMA,
    GENERATOR_QWEN,
    GENERATOR_TEMPLATE,
    ResponseGenerator,
)
from bot.services.ghosteek_ai.generator.llm_generator import (
    OllamaResponseGenerator,
    QwenResponseGenerator,
)
from bot.services.ghosteek_ai.generator.response import TemplateResponseGenerator

# Alias по ТЗ
TemplateGenerator = TemplateResponseGenerator

_DEFAULT_TEMPLATE = TemplateResponseGenerator()


def get_response_generator(backend: str | None = None) -> ResponseGenerator:
    """Вернуть генератор. Модель не вызывается.

    backend:
      - "template" (default) → TemplateResponseGenerator (рабочий)
      - "ollama" → OllamaResponseGenerator (NotImplemented до HTTP)
      - "qwen" → QwenResponseGenerator (NotImplemented до клиента)
    """
    name = (backend or DEFAULT_GENERATOR).strip().lower()
    if name in {GENERATOR_QWEN, "dashscope"}:
        return QwenResponseGenerator()
    if name in {GENERATOR_OLLAMA, "local"}:
        return OllamaResponseGenerator()
    if name in {GENERATOR_TEMPLATE, "default", ""}:
        return _DEFAULT_TEMPLATE
    # неизвестный backend → безопасный default, без смены поведения
    return _DEFAULT_TEMPLATE
