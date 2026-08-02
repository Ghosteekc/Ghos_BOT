"""Response Generator package.

TODO(Qwen): добавить QwenResponseGenerator(AIContext) -> str рядом с TemplateResponseGenerator.
"""

from bot.services.ghosteek_ai.generator.response import (
    TemplateResponseGenerator,
    compose_answer_from_payload,
    generate_response,
)

__all__ = [
    "TemplateResponseGenerator",
    "compose_answer_from_payload",
    "generate_response",
]
