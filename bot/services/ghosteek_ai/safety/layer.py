"""Safety Layer — post-validation ответа против AIContext."""

from __future__ import annotations

from bot.services.ghosteek_ai.constraints import (
    CONSTRAINTS_SUMMARY,
    enforce_answer,
    sanitize_answer,
)
from bot.services.ghosteek_ai.models import AIContext
from bot.services.ghosteek_ai.safety.facts import extract_allowed_facts
from bot.services.ghosteek_ai.safety.local_renderer_validator import (
    LOCAL_RENDERER_INVALID_FALLBACK,
    apply_local_renderer_gate,
)
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

    Cloud pipeline:
      validate_language → battle → statistics → numbers
      → enforce_answer → coach voice + ending → word limit

    Local renderer (ctx.render_facts):
      assert_coach_voice → enforce_answer (стиль)
      → deterministic facts-only gate (invalid → fallback, без эвристик)
      → word limit
      Cloud validators / rewrite НЕ применяются (иначе «чинят» галлюцинации).
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
        render_facts = getattr(ctx, "render_facts", None) if ctx is not None else None

        if render_facts is not None:
            # Local Qwen3: строгий gate, без эвристического «починка» текста.
            out = assert_coach_voice(out)
            out = enforce_answer(out)
            gated = apply_local_renderer_gate(out, render_facts, ctx=ctx)
            # Если LLM сорвался, а ToolResult уже есть — лучше шаблон, чем холодный fallback.
            if gated == LOCAL_RENDERER_INVALID_FALLBACK and ctx is not None:
                tool = str((render_facts or {}).get("tool") or "").strip().lower()
                if tool in {"capability", "chat"}:
                    from bot.services.ghosteek_ai.intents import (
                        CHAT_FALLBACK_PROMPTS,
                        CLARIFY_PROMPT,
                    )

                    seed = (getattr(ctx, "raw_message", None) or "") + tool
                    idx = abs(hash(seed)) % len(CHAT_FALLBACK_PROMPTS)
                    out = assert_coach_voice(CHAT_FALLBACK_PROMPTS[idx] or CLARIFY_PROMPT)
                elif getattr(ctx, "ok", False):
                    from bot.services.ghosteek_ai.generator.response import (
                        TemplateResponseGenerator,
                    )

                    templated = TemplateResponseGenerator().generate(ctx)
                    out = templated if templated.strip() else gated
                else:
                    out = gated
            else:
                out = gated
            intent = None
            if ctx is not None:
                intent = getattr(getattr(ctx, "intent", None), "request", None)
            if out != LOCAL_RENDERER_INVALID_FALLBACK:
                out = trim_to_word_limit(out, word_limit_for(intent))
            if len(out) > cls.MAX_CHARS:
                out = out[: cls.MAX_CHARS - 1].rstrip() + "…"
            return out

        # Cloud / template path — без изменений.
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
