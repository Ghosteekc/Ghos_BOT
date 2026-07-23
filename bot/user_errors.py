"""Пользовательские сообщения об ошибках с кодами для администратора."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

DEFAULT_UNAVAILABLE = (
    "В данный момент сервер не отвечает. Подождите или зайдите позже."
)

# Код -> текст для пользователя (без технических деталей)
MESSAGES: dict[str, str] = {
    # Ввод / состояние
    "E001": "Неверный формат тега. Используйте символы: 0289PYLQGRJCUV",
    "E002": "Игрок с таким тегом не найден. Проверьте тег и попробуйте снова.",
    "E003": "Тег не привязан. Нажмите «Регистрация» или отправьте /link",
    "E004": "Бой не найден. Обновите список боёв и попробуйте снова.",
    "E005": "Соперник не найден. Обновите данные и попробуйте снова.",
    "E006": "Колода не найдена в последних боях.",
    # Clash Royale API
    "E010": DEFAULT_UNAVAILABLE,
    "E011": DEFAULT_UNAVAILABLE,
    "E012": DEFAULT_UNAVAILABLE,
    # Загрузка данных
    "E020": DEFAULT_UNAVAILABLE,
    "E021": DEFAULT_UNAVAILABLE,
    # База данных
    "E030": DEFAULT_UNAVAILABLE,
    # Анализ / расчёты
    "E040": DEFAULT_UNAVAILABLE,
    "E041": DEFAULT_UNAVAILABLE,
    "E042": DEFAULT_UNAVAILABLE,
    # Колоды / кастомизация
    "E050": DEFAULT_UNAVAILABLE,
    "E051": DEFAULT_UNAVAILABLE,
    "E052": DEFAULT_UNAVAILABLE,
    "E053": DEFAULT_UNAVAILABLE,
    # Профиль / привязка
    "E060": DEFAULT_UNAVAILABLE,
    "E061": DEFAULT_UNAVAILABLE,
    "E062": "Этот аккаунт Clash Royale уже привязан к другому пользователю Telegram.",
    # Админ
    "E080": DEFAULT_UNAVAILABLE,
    # Авторизация Mini App
    "E090": "Не удалось войти в приложение. Перезапустите Mini App из Telegram.",
    "E091": "Сессия Telegram истекла. Закройте и снова откройте приложение.",
    "E092": "Тег игрока не привязан. Привяжите аккаунт в боте: /link",
    "E093": "Доступ запрещён.",
    # Поддержка / прочее
    "E900": "Поддержка временно недоступна. Попробуйте позже.",
    "E099": DEFAULT_UNAVAILABLE,
}


def user_message(code: str, text: str | None = None) -> str:
    """Текст ошибки для Telegram (HTML)."""
    body = text or MESSAGES.get(code, DEFAULT_UNAVAILABLE)
    return f"❌ {body}\n\n🔢 Код ошибки: <code>{code}</code>"


def user_message_plain(code: str, text: str | None = None) -> str:
    """Текст ошибки без HTML (Mini App, alert)."""
    body = text or MESSAGES.get(code, DEFAULT_UNAVAILABLE)
    return f"{body}\n\nКод ошибки: {code}"


def log_error(
    logger: logging.Logger,
    code: str,
    technical: str,
    *,
    exc: BaseException | None = None,
    **context: Any,
) -> None:
    parts = [f"[{code}]", technical]
    if context:
        parts.append("| " + " ".join(f"{k}={v}" for k, v in context.items()))
    line = " ".join(parts)
    if exc is not None:
        logger.error(line, exc_info=True)
    else:
        logger.error(line)


def code_from_clash_api(exc: Any) -> str:
    """Сопоставить ClashRoyaleAPIError с кодом для пользователя."""
    from bot.services.clash_api import ClashRoyaleAPIError

    if not isinstance(exc, ClashRoyaleAPIError):
        return "E099"
    if exc.status == 404:
        return "E002"
    if exc.config_error:
        return "E010"
    if exc.status == 429:
        return "E012"
    if exc.retryable or exc.status == 0:
        return "E011"
    return "E020"


def http_error(code: str, status: int = 503, message: str | None = None) -> HTTPException:
    """HTTPException с безопасным телом для Mini App."""
    return HTTPException(
        status_code=status,
        detail={
            "message": message or MESSAGES.get(code, DEFAULT_UNAVAILABLE),
            "code": code,
        },
    )


def http_error_from_clash(exc: Any, *, status: int | None = None) -> HTTPException:
    code = code_from_clash_api(exc)
    http_status = status
    if http_status is None:
        if code == "E002":
            http_status = 404
        elif code in {"E010", "E011", "E012"}:
            http_status = 503
        else:
            http_status = 502
    return http_error(code, status=http_status)
