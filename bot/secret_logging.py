"""Redact configured credentials from application log records and tracebacks."""

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


def _redact(text: str) -> str:
    for value in _protected_values:
        text = text.replace(value, "[REDACTED]")
    text = _BETA_INVITE.sub("beta_[REDACTED]", text)
    return _INVOICE_PAYLOAD.sub("ghosteek_pro:[REDACTED]", text)


def _redact_arg(value: object) -> object:
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


def _safe_record_factory(*args: object, **kwargs: object) -> logging.LogRecord:
    record = _previous_factory(*args, **kwargs)
    if type(record) is logging.LogRecord:
        record.__class__ = _RedactingLogRecord
    if isinstance(record.msg, str):
        record.msg = _redact(record.msg)
    record.args = _redact_arg(record.args)
    if record.exc_info:
        details = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        record.exc_text = _redact(details)
    if record.stack_info:
        record.stack_info = _redact(record.stack_info)
    return record


def _safe_excepthook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    """Keep an uncaught traceback useful without printing credentials to stderr."""
    sys.stderr.write(_redact("".join(traceback.format_exception(exc_type, exc, tb))))


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
