"""Ограничения Ghosteek AI — только факты из разрешённых источников."""

from __future__ import annotations

import re

from bot.services.ghosteek_ai.voice import coach_reply

# Разрешённые основания для ответа
ALLOWED_SOURCES = (
    "supercell_api",       # Clash Royale / Supercell API
    "project_analysis",    # Analyzer, Matchup, Battle report, Recommendation…
    "card_database",       # card profile / names / roles
    "meta",                # meta decks / templates
    "user_data",           # профиль, история боёв, сессия
)

CONSTRAINTS_SUMMARY = (
    "Отвечаю только по данным Supercell API, анализу Ghosteek, карточной базе, "
    "мете и твоим данным. Не выдумываю статистику, урон и то, чего нет в API."
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


def is_unsupported_request(message: str) -> bool:
    """True, если запрос требует данных, которых нет у CR API / наших сервисов."""
    return bool(_UNSUPPORTED_REQUEST_RE.search(message or ""))


def refuse_unsupported(*, detail: str | None = None) -> str:
    """Честный отказ без выдуманных цифр."""
    why = detail or (
        "Supercell API не отдаёт точный урон карт в бою, эликсир в руке, "
        "кадры реплея и счётчики «сколько раз сыграли карту» в матче."
    )
    return coach_reply(
        "Этих данных нет — не буду выдумывать.",
        why=why,
        action=(
            "Могу опереться на API, разбор колоды/боя/матчапа Ghosteek, "
            "карточную базу, мету и твои сохранённые данные."
        ),
        tip=CONSTRAINTS_SUMMARY,
    )


def contains_forbidden_claim(text: str) -> bool:
    return bool(_FORBIDDEN_CLAIM_RE.search(text or ""))


def sanitize_answer(text: str) -> str:
    """Убрать/заменить запрещённые утверждения, если они вдруг попали в ответ."""
    raw = (text or "").strip()
    if not raw:
        return raw
    if not contains_forbidden_claim(raw):
        return raw
    # Не пытаемся «починить» галлюцинацию — честно режем
    return coach_reply(
        "Тут я чуть не сказал лишнего.",
        why="Точных кадров боя, урона карт и счётчиков розыгрышей в API нет.",
        action="Опирайся на разбор колоды, матчап и сохранённую историю боёв.",
        tip=CONSTRAINTS_SUMMARY,
    )


def enforce_answer(text: str, *, intent: str | None = None) -> str:
    """Финальный фильтр исходящего ответа."""
    del intent  # reserved for intent-specific rules
    return sanitize_answer(text)
