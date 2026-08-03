"""Factory ResponseGenerator — template / ollama / qwen по конфигу."""

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


def _backend_from_settings() -> str:
    try:
        from bot.config import settings

        return (settings.ghosteek_ai_backend or DEFAULT_GENERATOR).strip().lower()
    except Exception:
        return DEFAULT_GENERATOR


def get_response_generator(backend: str | None = None) -> ResponseGenerator:
    """Вернуть генератор по имени или из settings.ghosteek_ai_backend.

    backend:
      - "template" → TemplateGenerator (fallback)
      - "qwen" / "dashscope" / "openai" → QwenGenerator (OpenAI-compatible)
      - "ollama" / "local" → OllamaResponseGenerator
    """
    name = (backend if backend is not None else _backend_from_settings()).strip().lower()
    if name in {GENERATOR_QWEN, "dashscope", "openai", "openai_compatible"}:
        return QwenResponseGenerator()
    if name in {GENERATOR_OLLAMA, "local"}:
        return OllamaResponseGenerator()
    if name in {GENERATOR_TEMPLATE, "default", ""}:
        return _DEFAULT_TEMPLATE
    return _DEFAULT_TEMPLATE


def get_template_generator() -> TemplateResponseGenerator:
    return _DEFAULT_TEMPLATE
