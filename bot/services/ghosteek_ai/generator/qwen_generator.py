"""QwenResponseGenerator — заглушка под будущий LLM.

Модель НЕ подключена. Не вызывать в прод-пайплайне, пока нет клиента Qwen.
"""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.voice import SYSTEM_PROMPT


class QwenResponseGenerator:
    """Генератор ответа через Qwen (не реализован).

    Когда подключать:
      1) SYSTEM_PROMPT + ctx.to_llm_dict() → messages
      2) (опционально) второй проход после tool_calls
      3) вернуть текст → SafetyLayer.apply

    Сейчас generate() поднимает NotImplementedError, чтобы случайно
    не включить пустой бэкенд.
    """

    backend = "qwen"

    def generate(self, ctx: AIContext) -> str:
        del ctx  # reserved: ctx.to_llm_dict() + SYSTEM_PROMPT
        _ = SYSTEM_PROMPT  # referenced for future wiring
        raise NotImplementedError(
            "QwenResponseGenerator is not connected yet. "
            "Use TemplateResponseGenerator / get_response_generator('template'). "
            "Hook: bot.services.ghosteek_ai.generator.qwen_generator.QwenResponseGenerator.generate"
        )


# Alias по ТЗ
QwenGenerator = QwenResponseGenerator
