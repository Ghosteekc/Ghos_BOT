"""Системная личность Ghosteek AI — профессиональный тренер Clash Royale."""

from __future__ import annotations

PERSONA = (
    "Ghosteek AI — профессиональный тренер Clash Royale. "
    "Дружелюбный, спокойный, уверенный. Без воды и длинных вступлений. "
    "Отвечает как тренер игроку: коротко, по делу, человеческим языком."
)

# Фразы, которых не должно быть в ответах игроку
BANNED_SNIPPETS = (
    "как ии",
    "как ai",
    "я искусственн",
    "языковая модель",
    "как нейросеть",
    "recommendationengine",
    "в качестве ии",
)


def coach_reply(
    verdict: str,
    *,
    why: str = "",
    action: str = "",
    tip: str = "",
) -> str:
    """Структура ответа: вывод → почему → что делать → практический совет.

    Без заголовков-лейблов — просто короткие абзацы, как говорит тренер.
    """
    parts: list[str] = []
    for block in (verdict.strip(), why.strip(), action.strip(), tip.strip()):
        if block:
            parts.append(block)
    text = "\n\n".join(parts)
    return text.strip() or "Давай уточним задачу — так я смогу дать точный совет."


def assert_coach_voice(text: str) -> str:
    """Мягкая зачистка запрещённых формулировок (на всякий случай)."""
    low = text.lower()
    for ban in BANNED_SNIPPETS:
        if ban in low:
            # Не подставляем «как ИИ» обратно — просто оставляем текст как есть
            # после нормализации очевидных кусков.
            text = text.replace("Как ИИ", "").replace("как ИИ", "")
            break
    return text.strip()
