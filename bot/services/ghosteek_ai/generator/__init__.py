"""Response Generator package.

Интерфейс: ResponseGenerator
Реализации: TemplateResponseGenerator (alias TemplateGenerator),
            OllamaResponseGenerator / QwenResponseGenerator.
"""

from bot.services.ghosteek_ai.generator.base import (
    DEFAULT_GENERATOR,
    GENERATOR_OLLAMA,
    GENERATOR_QWEN,
    GENERATOR_TEMPLATE,
    ResponseGenerator,
)
from bot.services.ghosteek_ai.generator.factory import (
    get_response_generator,
    get_template_generator,
)
from bot.services.ghosteek_ai.generator.llm_generator import (
    LLMResponseGenerator,
    OllamaGenerator,
    OllamaResponseGenerator,
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
    "LLMResponseGenerator",
    "OllamaResponseGenerator",
    "OllamaGenerator",
    "QwenResponseGenerator",
    "QwenGenerator",
    "get_response_generator",
    "get_template_generator",
    "generate_response",
    "compose_answer_from_payload",
    "DEFAULT_GENERATOR",
    "GENERATOR_TEMPLATE",
    "GENERATOR_OLLAMA",
    "GENERATOR_QWEN",
]
