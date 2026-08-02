"""Safety Layer — проверки исходящего ответа."""

from __future__ import annotations

from bot.services.ghosteek_ai.constraints import (
    CONSTRAINTS_SUMMARY,
    enforce_answer,
    sanitize_answer,
)
from bot.services.ghosteek_ai.models import AIContext
from bot.services.ghosteek_ai.voice import PERSONA, assert_coach_voice


class SafetyLayer:
    """Факты / запреты / стиль / длина / терминология.

    TODO(Qwen): усилить hallucination check против AIContext (сверка чисел
    score/synergy только если они есть в ctx.data).
    """

    MAX_CHARS = 3500

    @classmethod
    def apply(cls, text: str, ctx: AIContext | None = None) -> str:
        del ctx  # reserved for fact-check against AIContext
        out = enforce_answer(text)
        out = assert_coach_voice(out)
        if len(out) > cls.MAX_CHARS:
            out = out[: cls.MAX_CHARS - 1].rstrip() + "…"
        return out


__all__ = [
    "SafetyLayer",
    "CONSTRAINTS_SUMMARY",
    "PERSONA",
    "sanitize_answer",
]
