"""Redact credentials and personal identifiers from logs, not application data."""

from __future__ import annotations

import logging
import re
import sys
import traceback
from types import TracebackType
from urllib.parse import parse_qsl, quote, quote_plus, unquote, urlsplit

_previous_factory = logging.getLogRecordFactory()
_protected_values: tuple[str, ...] = ()
_BETA_INVITE = re.compile(r"\bbeta_[0-9a-f]{16,32}\b", re.IGNORECASE)
_INVOICE_PAYLOAD = re.compile(r"\bghosteek_pro:[^\s,)'\"]+")
_SENSITIVE_QUERY_KEY = re.compile(r"(?:password|passwd|token|secret|api[_-]?key|auth)", re.IGNORECASE)
_PERSONAL_ID = re.compile(
    r"\b(telegram[_-]?id|user[_-]?id|chat[_-]?id|payload_tg|referrer_tg|"
    r"referred|from|user|by)([\"']?\s*[=:]\s*[\"']?)-?\d{1,20}\b",
    re.IGNORECASE,
)
_PERSONAL_ID_PHRASE = re.compile(r"\b(user|telegram user|chat)(\s+)\d{3,20}\b", re.IGNORECASE)
_PLAYER_TAG = re.compile(r"(?<![\w])(?:#|%23)[A-Z0-9]{3,20}\b", re.IGNORECASE)
_TELEGRAM_HANDLE = re.compile(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_]{4,31}\b")
_IDENTITY_VALUE = re.compile(
    r"\b(username|player_tag|tag|first_name|last_name)([\"']?\s*[=:]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;)}]+)", re.IGNORECASE,
)
_DB_DETAIL = re.compile(r"(Key \([^)]+\)=)\([^\r\n]*?\)(?= (?:already exists|is not present))")
_PLAYER_PATH = re.compile(r"(/(?:players|clans)/)[^\s/?\"']+", re.IGNORECASE)


def _redact(text: str) -> str:
    for value in _protected_values:
        text = text.replace(value, "[REDACTED]")
    text = _BETA_INVITE.sub("beta_[REDACTED]", text)
    text = _INVOICE_PAYLOAD.sub("ghosteek_pro:[REDACTED]", text)
    text = _DB_DETAIL.sub(r"\1([REDACTED])", text)
    text = _PLAYER_PATH.sub(r"\1[REDACTED]", text)
    text = _IDENTITY_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _PERSONAL_ID.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _PERSONAL_ID_PHRASE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _PLAYER_TAG.sub("#[REDACTED]", text)
    return _TELEGRAM_HANDLE.sub("@[REDACTED]", text)


def _redact_arg(value: object) -> object:
    if isinstance(value, BaseException) and type(value).__module__.startswith("bot.services.ghosteek_ai"):
        return _exception_text(type(value), value, None)
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, tuple):
        return tuple(_redact_arg(item) for item in value)
    if isinstance(value, dict):
        return {key: _redact_arg(item) for key, item in value.items()}
    return value


class _RedactingLogRecord(logging.LogRecord):
    def getMessage(self) -> str:
        return _redact(super().getMessage())


def _exception_text(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> str:
    # Provider exceptions can embed full upstream bodies (including echoed user text).
    # Keep stack locations and a bounded error code, without changing the exception.
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__module__.startswith("bot.services.ghosteek_ai"):
            code = str(getattr(current, "code", ""))
            safe_code = code if re.fullmatch(r"[A-Z_0-9]{1,64}", code) else "UPSTREAM_ERROR"
            return _redact("".join(traceback.format_tb(tb)) + f"{exc_type.__name__}: {safe_code}")
        current = current.__cause__ or current.__context__
    return _redact("".join(traceback.format_exception(exc_type, exc, tb)))


def _safe_record_factory(*args: object, **kwargs: object) -> logging.LogRecord:
    record = _previous_factory(*args, **kwargs)
    if type(record) is logging.LogRecord:
        record.__class__ = _RedactingLogRecord
    # Do not redact placeholders (e.g. username=%s) before interpolation.
    if isinstance(record.msg, str) and not record.args:
        record.msg = _redact(record.msg)
    record.args = _redact_arg(record.args)
    # Uvicorn's AccessFormatter unpacks this tuple: preserve its shape/types.
    # Query strings may contain initData and identifiers; client IP is unnecessary here.
    if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
        _, method, path, version, status = record.args
        record.args = ("[REDACTED]", method, _redact(str(path).partition("?")[0]), version, status)
    if record.exc_info:
        record.exc_text = _exception_text(*record.exc_info).rstrip()
    if record.stack_info:
        record.stack_info = _redact(record.stack_info)
    return record


def _safe_excepthook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    """Keep an uncaught traceback useful without printing credentials to stderr."""
    sys.stderr.write(_exception_text(exc_type, exc, tb))


def install_secret_redaction(settings: object) -> None:
    """Protect every logging handler, including handlers added after startup."""
    global _previous_factory, _protected_values

    values = [
        getattr(settings, name, None)
        for name in (
            "database_url",
            "bot_token",
            "clash_royale_api_key",
            "clash_royale_proxy_secret",
            "llm_api_key",
        )
    ]
    database_url = getattr(settings, "database_url", "") or ""
    for url in (
        database_url,
        getattr(settings, "clash_royale_api_base", ""),
        getattr(settings, "llm_base_url", ""),
        getattr(settings, "ollama_url", ""),
        getattr(settings, "webapp_url", ""),
    ):
        if not url:
            continue
        try:
            parsed = urlsplit(url)
            if parsed.password:
                values.extend((parsed.password, unquote(parsed.password)))
            for key, value in parse_qsl(parsed.query, keep_blank_values=False):
                if _SENSITIVE_QUERY_KEY.search(key):
                    values.append(value)
        except ValueError:
            continue

    variants: set[str] = set()
    for value in values:
        if not value:
            continue
        secret = str(value)
        variants.update((secret, quote(secret, safe=""), quote_plus(secret)))
    _protected_values = tuple(sorted(variants - {""}, key=len, reverse=True))

    if logging.getLogRecordFactory() is not _safe_record_factory:
        _previous_factory = logging.getLogRecordFactory()
        logging.setLogRecordFactory(_safe_record_factory)
    if sys.excepthook is not _safe_excepthook:
        sys.excepthook = _safe_excepthook
