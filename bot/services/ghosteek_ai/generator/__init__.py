"""Response Generator package.

Интерфейс: ResponseGenerator
Реализации: TemplateResponseGenerator (alias TemplateGenerator),
            QwenResponseGenerator (stub, модель не подключена).
"""

from bot.services.ghosteek_ai.generator.base import (
    DEFAULT_GENERATOR,
    GENERATOR_QWEN,
    GENERATOR_TEMPLATE,
    ResponseGenerator,
)
from bot.services.ghosteek_ai.generator.factory import get_response_generator
from bot.services.ghosteek_ai.generator.qwen_generator import (
    QwenGenerator,
    QwenResponseGenerator,
)
from bot.services.ghosteek_ai.generator.response import (
    TemplateGenerator,
    TemplateResponseGenerator,
    compose_answer_from_payload,
    generate_response,
)

__all__ = [
    "ResponseGenerator",
    "TemplateResponseGenerator",
    "TemplateGenerator",
    "QwenResponseGenerator",
    "QwenGenerator",
    "get_response_generator",
    "generate_response",
    "compose_answer_from_payload",
    "DEFAULT_GENERATOR",
    "GENERATOR_TEMPLATE",
    "GENERATOR_QWEN",
]
