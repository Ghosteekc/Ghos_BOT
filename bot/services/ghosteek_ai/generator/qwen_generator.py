"""QwenResponseGenerator — stub через LLM-слой (модель не подключена).

Реэкспорт из generator.llm_generator для обратной совместимости.
Прод-пайплайн использует TemplateResponseGenerator.
"""

from __future__ import annotations

from bot.services.ghosteek_ai.generator.llm_generator import (
    QwenGenerator,
    QwenResponseGenerator,
)

__all__ = ["QwenResponseGenerator", "QwenGenerator"]
