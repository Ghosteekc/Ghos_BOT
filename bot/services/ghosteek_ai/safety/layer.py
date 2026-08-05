"""Safety Layer — post-validation ответа против AIContext."""

from __future__ import annotations

from bot.services.ghosteek_ai.constraints import (
    CONSTRAINTS_SUMMARY,
    enforce_answer,
    sanitize_answer,
)
from bot.services.ghosteek_ai.models import AIContext
from bot.services.ghosteek_ai.safety.facts import extract_allowed_facts
from bot.services.ghosteek_ai.safety.validators import (
    validate_battle_claims,
    validate_language,
    validate_numbers,
    validate_statistics,
)
from bot.services.ghosteek_ai.voice import (
    PERSONA,
    SYSTEM_PROMPT,
    assert_coach_voice,
    ensure_coach_ending,
    trim_to_word_limit,
    word_limit_for,
)


class SafetyLayer:
    """Факты / запреты / стиль / длина / терминология.

    Pipeline:
      validate_language
      → validate_battle_claims
      → validate_statistics
      → validate_numbers
      → enforce_answer (jargon + остаточные forbidden)
      → coach voice + ending + word limit
    """

    MAX_CHARS = 1200

    VALIDATORS = (
        validate_language,
        validate_battle_claims,
        validate_statistics,
        validate_numbers,
    )

    @classmethod
    def apply(cls, text: str, ctx: AIContext | None = None) -> str:
        out = (text or "").strip()
        facts = extract_allowed_facts(ctx)
        for validator in cls.VALIDATORS:
            out = validator(out, ctx, facts=facts)
        out = enforce_answer(out)
        out = ensure_coach_ending(assert_coach_voice(out))
        intent = None
        if ctx is not None:
            intent = getattr(getattr(ctx, "intent", None), "request", None)
        out = trim_to_word_limit(out, word_limit_for(intent))
        if len(out) > cls.MAX_CHARS:
            out = out[: cls.MAX_CHARS - 1].rstrip() + "…"
        return out


__all__ = [
    "SafetyLayer",
    "CONSTRAINTS_SUMMARY",
    "PERSONA",
    "SYSTEM_PROMPT",
    "sanitize_answer",
]
