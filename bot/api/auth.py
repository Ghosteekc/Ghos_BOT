"""Telegram Mini App initData validation (HMAC-SHA256)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(Exception):
    """Невалидные или просроченные данные initData."""


@dataclass(frozen=True)
class ValidatedInitData:
    user: dict
    auth_date: int
    query_id: str | None
    signature: str


def validate_auth_date(
    auth_date: int,
    *,
    max_age_seconds: int,
    clock_skew_seconds: int = 60,
    now: float | None = None,
) -> None:
    """Проверка свежести initData.

    Replay внутри TTL — нормальное поведение Mini App: клиент шлёт один и тот же
    initData на каждый запрос до перезапуска WebApp. Защита — HMAC + auth_date TTL,
    а не одноразовый hash.
    """
    if auth_date <= 0:
        raise InitDataError("Некорректная дата авторизации Telegram")

    now_ts = now if now is not None else time.time()
    if auth_date > now_ts + clock_skew_seconds:
        raise InitDataError("Некорректная дата авторизации Telegram")

    if now_ts - auth_date > max_age_seconds:
        raise InitDataError("Сессия Telegram истекла — перезапустите приложение")


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 86400,
    clock_skew_seconds: int = 60,
) -> dict:
    """Validate Telegram WebApp initData per official docs. Returns user dict."""
    validated = validate_init_data_full(
        init_data,
        bot_token,
        max_age_seconds=max_age_seconds,
        clock_skew_seconds=clock_skew_seconds,
    )
    return validated.user


def validate_init_data_full(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 86400,
    clock_skew_seconds: int = 60,
) -> ValidatedInitData:
    if not init_data or not init_data.strip():
        raise InitDataError("Нет данных авторизации Telegram")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise InitDataError("Ошибка авторизации Telegram")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise InitDataError("Неверная подпись Telegram")

    try:
        auth_date = int(parsed.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("Некорректная дата авторизации Telegram") from exc

    validate_auth_date(
        auth_date,
        max_age_seconds=max_age_seconds,
        clock_skew_seconds=clock_skew_seconds,
    )

    user_raw = parsed.get("user")
    if not user_raw:
        raise InitDataError("Не удалось определить пользователя Telegram")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise InitDataError("Некорректные данные пользователя Telegram") from exc

    if "id" not in user:
        raise InitDataError("Некорректные данные пользователя Telegram")

    return ValidatedInitData(
        user=user,
        auth_date=auth_date,
        query_id=parsed.get("query_id"),
        signature=received_hash,
    )
