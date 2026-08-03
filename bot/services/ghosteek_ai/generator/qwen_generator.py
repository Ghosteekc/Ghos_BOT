"""QwenResponseGenerator — LLM через OpenAI-compatible Chat Completions.

Реэкспорт из generator.llm_generator.
"""

from __future__ import annotations

from bot.services.ghosteek_ai.generator.llm_generator import (
    QwenGenerator,
    QwenResponseGenerator,
)

__all__ = ["QwenResponseGenerator", "QwenGenerator"]
