"""Ограничения Ghosteek AI — только факты из разрешённых источников.

Важно: в текстах для игрока не используем слова API, Analyzer, Builder
и прочие внутрипроектовые ярлыки.
"""

from __future__ import annotations

import re

from bot.services.ghosteek_ai.voice import coach_reply

# Разрешённые основания (внутренние коды, не для UI)
ALLOWED_SOURCES = (
    "supercell_api",
    "project_analysis",
    "card_database",
    "meta",
    "user_data",
)

# Коротко и по-человечески — без «API» и названий модулей
CONSTRAINTS_SUMMARY = (
    "Опираюсь на состав, матчап и твою историю боёв. "
    "Урон карт, эликсир в руке и кадры реплея в данных нет — не выдумываю."
)

# Запросы, на которые нельзя честно ответить без выдумки
_UNSUPPORTED_REQUEST_RE = re.compile(
    r"("
    r"урон\s+по\s+карт|"
    r"сколько\s+урона|"
    r"нанесл[аои]?\s+урон|"
    r"damage\s+(per|dealt|to)|"
    r"дпс\b|"
    r"dps\b|"
    r"эликсир(а|у)?\s+в\s+рук|"
    r"сколько\s+эликсир|"
    r"elixir\s+in\s+hand|"
    r"hp\s+башн|"
    r"хп\s+башн|"
    r"точн(ый|ое|ые)\s+(хп|hp|урон|стат)|"
    r"кадры\s+боя|"
    r"replay\s+frame|"
    r"видел\s+реплей|"
    r"посмотри\s+реплей|"
    r"разбери\s+реплей|"
    r"из\s+репле|"
    r"сколько\s+раз\s+(сыграл|кинул|поставил|использовал)|"
    r"сколько\s+раз\s+была\s+сыграна|"
    r"times?\s+played|"
    r"card\s+usage\s+in\s+(the\s+)?battle|"
    r"использование\s+карт(ы|и)?\s+в\s+бою|"
    r"в\s+какую\s+секунд|"
    r"на\s+какой\s+секунд|"
    r"порядок\s+карт\s+в\s+руке|"
    r"какая\s+карта\s+была\s+в\s+руке|"
    r"придумай\s+статистик|"
    r"выдумай\s+урон|"
    r"fake\s+stats"
    r")",
    re.IGNORECASE,
)

# Запрещённые утверждения в исходящем тексте (галюцинации)
_FORBIDDEN_CLAIM_RE = re.compile(
    r"("
    r"я\s+видел\s+реплей|"
    r"посмотрел\s+реплей|"
    r"по\s+реплею\s+видно|"
    r"в\s+реплее\s+(было|карта)|"
    r"карта\s+нанесла\s+\d|"
    r"нанесла?\s+\d+[\s.,]?\d*\s*(урона|dmg|damage)|"
    r"сыграл[аи]?\s+\d+\s+раз|"
    r"использовал[аи]?\s+\d+\s+раз|"
    r"в\s+руке\s+было\s+\d|"
    r"эликсир\s+в\s+руке\s+был|"
    r"точно\s+\d+\s*hp|"
    r"dps\s*=\s*\d|"
    r"статистика\s+показывает\s+\d+%\s+винрейт\s+этой\s+карты\s+в\s+этом\s+бою"
    r")",
    re.IGNORECASE,
)

# Внутрипроектовый жаргон — вычищаем из ответов игроку
_INTERNAL_JARGON_RE = re.compile(
    r"("
    r"\bAPI\b|"
    r"Supercell\s+API|"
    r"Clash\s+Royale\s+API|"
    r"CR\s+API|"
    r"RecommendationEngine|"
    r"Matchup\s*Analyzer|"
    r"Battle\s*Analyzer|"
    r"Knowledge\s*Base|"
    r"Card\s*Database|"
    r"Game\s*Coach|"
    r"Session\s*Context|"
    r"\bBuilder\b|"
    r"\bAnalyzer\b|"
    r"HonestFallback|"
    r"intent\s*:"
    r")",
    re.IGNORECASE,
)


def is_unsupported_request(message: str) -> bool:
    """True, если запрос требует данных, которых у нас нет."""
    return bool(_UNSUPPORTED_REQUEST_RE.search(message or ""))


def refuse_unsupported(*, detail: str | None = None) -> str:
    """Честный отказ без выдуманных цифр и без внутренних терминов."""
    why = detail or (
        "В доступных данных боя нет точного урона карт, эликсира в руке, "
        "кадров реплея и счётчика «сколько раз сыграли карту»."
    )
    return coach_reply(
        "Этих данных нет — не буду выдумывать цифры.",
        why=why,
        action="Могу разобрать колоду, матчап, бой или объяснить механику по делу.",
        tip="Сформулируй вопрос через карты, матчап или последний бой — там совет точнее.",
    )


def contains_forbidden_claim(text: str) -> bool:
    return bool(_FORBIDDEN_CLAIM_RE.search(text or ""))


def strip_internal_jargon(text: str) -> str:
    """Убрать/смягчить внутрипроектовые ярлыки в тексте для игрока."""
    if not text:
        return text

    replacements = (
        (r"Clash\s+Royale\s+API", "доступные данные"),
        (r"Supercell\s+API", "доступные данные"),
        (r"CR\s+API", "доступные данные"),
        (r"\bAPI\b", "данные"),
        (r"RecommendationEngine", "разбор"),
        (r"Matchup\s*Analyzer", "разбор матчапа"),
        (r"Battle\s*Analyzer", "разбор боя"),
        (r"Knowledge\s*Base", "словарь терминов"),
        (r"Card\s*Database", "картотека"),
        (r"Game\s*Coach", "совет"),
        (r"Session\s*Context", "этот диалог"),
        (r"\bBuilder\b", "сборка колоды"),
        (r"\bAnalyzer\b", "разбор"),
        (r"из базы Ghosteek", "из наших шаблонов"),
        (r"базы Ghosteek", "готовых шаблонов"),
        (r"конструктором Ghosteek", "сборкой"),
        (r"конструктором", "сборкой"),
    )
    out = text
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    # подчистить двойные пробелы после замен
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def sanitize_answer(text: str) -> str:
    """Убрать запрещённые утверждения и внутренний жаргон."""
    raw = (text or "").strip()
    if not raw:
        return raw
    if contains_forbidden_claim(raw):
        return coach_reply(
            "Тут я чуть не сказал лишнего.",
            why="Точных кадров боя, урона карт и счётчиков розыгрышей в данных нет.",
            action="Опирайся на разбор колоды, матчап и историю боёв.",
            tip="Спроси через состав, матчап или последний бой — там совет будет по механике.",
        )
    return strip_internal_jargon(raw)


def enforce_answer(text: str, *, intent: str | None = None) -> str:
    """Финальный фильтр исходящего ответа."""
    del intent
    return sanitize_answer(text)
