"""ReasoningFilter — отделяет внутренние рассуждения LLM от ответа игроку.

Финальный текст пользователю проходит только если фильтр признаёт его
assistant answer, а не chain-of-thought / tool planning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReasoningVerdict:
    """Результат проверки текста модели."""

    is_final: bool
    reason: str = ""
    matched: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_final": self.is_final,
            "reason": self.reason,
            "matched": list(self.matched),
        }


# Английские маркеры внутреннего размышления / tool-planning.
_EN_PHRASES: tuple[str, ...] = (
    r"\bi need to\b",
    r"\bi should\b",
    r"\bi'll call\b",
    r"\bi will call\b",
    r"\bi'm going to call\b",
    r"\bi am going to call\b",
    r"\bthe user wants\b",
    r"\blooking at available tools\b",
    r"\bavailable tools\b",
    r"\blet'?s think\b",
    r"\blet us think\b",
    r"\bchain[- ]of[- ]thought\b",
    r"\breasoning\b",
    r"\bobservation\b",
    r"\bthought\s*:",
    r"\baction\s*:",
    r"\bobservation\s*:",
    r"\bsystem prompt\b",
    r"\bthe previous tool failed\b",
    r"\bi should call tool\b",
    r"\bcall the tool\b",
    r"\bcalling tool\b",
    r"\btool calls?\b",
    r"\bplanner\b",
    r"\bfunction call\b",
    r"\bas an ai\b",
    r"\bmy internal\b",
    r"\bstep[- ]by[- ]step\b",
    r"\bfirst,? i (?:will|need|should)\b",
)

# Русские маркеры внутреннего размышления / планирования tools.
_RU_PHRASES: tuple[str, ...] = (
    r"\bмне нужно\b",
    r"\bя должен\b",
    r"\bя должна\b",
    r"\bя вызову\b",
    r"\bвызову tool\b",
    r"\bвызову инструмент\b",
    r"\bпользователь хочет\b",
    r"\bдоступные tools\b",
    r"\bдоступные инструменты\b",
    r"\bдавай подумаем\b",
    r"\bдавайте подумаем\b",
    r"\bрассуждени[ея]\b",
    r"\bнаблюдени[ея]\b",
    r"\bмысль\s*:",
    r"\bдействие\s*:",
    r"\bсистемн\w* промпт\w*\b",
    r"\bпредыдущий tool\b",
    r"\bпредыдущий инструмент (?:упал|не сработал|failed)\b",
    r"\bвызов tool\b",
    r"\bвызов инструмента\b",
    r"\bпланер\b",
    r"\bкак (?:ии|ai|модель)\b",
    r"\bвнутренн(?:ий|ее|яя|его|ей) (?:рассуждени|монолог|мысл)",
    r"\bсначала (?:я |мне )?(?:вызову|посмотрю|проверю|нужно)\b",
)

_REACT_LINE = re.compile(
    r"(?im)^\s*(thought|action|observation|reasoning|plan|tool)\s*:",
)

_COMPILED: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.UNICODE) for p in (_EN_PHRASES + _RU_PHRASES)
)


@dataclass
class ReasoningFilter:
    """Проверяет, можно ли отдать текст модели пользователю."""

    extra_patterns: tuple[str, ...] = ()
    _extra: tuple[re.Pattern[str], ...] = field(default_factory=tuple, init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_extra",
            tuple(
                re.compile(p, re.IGNORECASE | re.UNICODE)
                for p in self.extra_patterns
                if p
            ),
        )

    def inspect(self, text: str | None) -> ReasoningVerdict:
        """Классифицировать текст: финальный ответ или внутреннее reasoning."""
        raw = (text or "").strip()
        if not raw:
            return ReasoningVerdict(is_final=False, reason="empty")

        matched: list[str] = []
        if _REACT_LINE.search(raw):
            matched.append("react_prefix")

        for pattern in _COMPILED + self._extra:
            if pattern.search(raw):
                matched.append(pattern.pattern)

        if matched:
            return ReasoningVerdict(
                is_final=False,
                reason="internal_reasoning",
                matched=tuple(matched[:8]),
            )
        return ReasoningVerdict(is_final=True, reason="ok")

    def is_internal_reasoning(self, text: str | None) -> bool:
        return not self.inspect(text).is_final

    def is_final_answer(self, text: str | None) -> bool:
        return self.inspect(text).is_final

    def accept_or_none(self, text: str | None) -> str | None:
        """Вернуть текст только если это финальный ответ игроку."""
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        if self.is_final_answer(cleaned):
            return cleaned
        return None


# Singleton для LLM-слоя
DEFAULT_REASONING_FILTER = ReasoningFilter()


def finalize_user_facing_text(
    *,
    content: str | None,
    reasoning: str | None = None,
    filter: ReasoningFilter | None = None,
) -> str | None:
    """Собрать текст для пользователя.

    - ``reasoning`` никогда не становится ответом игроку.
    - ``content`` проходит ReasoningFilter.
    - Если content пуст или похож на CoT → None (caller делает retry/fallback).
    """
    del reasoning  # явно: reasoning не для пользователя
    checker = filter or DEFAULT_REASONING_FILTER
    return checker.accept_or_none(content)


FINAL_ANSWER_RETRY_PROMPT = (
    "Ответь игроку финальным сообщением на русском языке. "
    "Без внутренних рассуждений, без упоминания tools/planner/system prompt, "
    "без фраз вроде «I need to» / «мне нужно вызвать». "
    "Только готовый ответ тренера Clash Royale."
)
