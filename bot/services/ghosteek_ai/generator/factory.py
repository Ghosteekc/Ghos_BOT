"""Factory ResponseGenerator — без подключения модели, default = template."""

from __future__ import annotations

from bot.services.ghosteek_ai.generator.base import (
    DEFAULT_GENERATOR,
    GENERATOR_QWEN,
    GENERATOR_TEMPLATE,
    ResponseGenerator,
)
from bot.services.ghosteek_ai.generator.qwen_generator import QwenResponseGenerator
from bot.services.ghosteek_ai.generator.response import TemplateResponseGenerator

# Alias по ТЗ
TemplateGenerator = TemplateResponseGenerator

_DEFAULT_TEMPLATE = TemplateResponseGenerator()


def get_response_generator(backend: str | None = None) -> ResponseGenerator:
    """Вернуть генератор. Модель не вызывается.

    backend:
      - "template" (default) → TemplateResponseGenerator
      - "qwen" → QwenResponseGenerator (NotImplemented до подключения)
    """
    name = (backend or DEFAULT_GENERATOR).strip().lower()
    if name in {GENERATOR_QWEN, "llm", "model"}:
        return QwenResponseGenerator()
    if name in {GENERATOR_TEMPLATE, "default", ""}:
        return _DEFAULT_TEMPLATE
    # неизвестный backend → безопасный default, без смены поведения
    return _DEFAULT_TEMPLATE
