"""Tests for Clash Royale API client helpers."""

from __future__ import annotations

from types import SimpleNamespace

from bot.services.clash_api import (
    ClashRoyaleAPIError,
    _config_error_message,
    _is_retryable_http_status,
    _parse_retry_after_header,
    _retry_delay_seconds,
)


def test_config_error_on_401() -> None:
    err = _config_error_message(401, '{"reason":"accessDenied"}')
    assert err.config_error is True
    assert err.status == 401
    assert err.retryable is False


def test_config_error_on_invalid_ip() -> None:
    err = _config_error_message(403, '{"reason":"invalidIp","ip":"1.2.3.4"}')
    assert err.config_error is True
    assert "1.2.3.4" in str(err)


def test_retry_backoff_increases() -> None:
    first = _retry_delay_seconds(None, 1)
    second = _retry_delay_seconds(None, 2)
    assert second >= first


def test_rate_limit_error_retryable() -> None:
    err = ClashRoyaleAPIError("rate limit", 429, retryable=True)
    assert err.retryable is True
    assert err.config_error is False


def test_retryable_statuses() -> None:
    assert _is_retryable_http_status(429) is True
    assert _is_retryable_http_status(503) is True
    assert _is_retryable_http_status(404) is False
    assert _is_retryable_http_status(401) is False
    assert _is_retryable_http_status(403) is False
    assert _is_retryable_http_status(400) is False


def test_retry_after_header_seconds() -> None:
    response = SimpleNamespace(headers={"Retry-After": "2.5"})
    assert _parse_retry_after_header(response) == 2.5
    assert _retry_delay_seconds(response, 1) == 2.5


def test_not_found_not_retryable() -> None:
    err = ClashRoyaleAPIError("missing", 404)
    assert err.retryable is False
    assert err.config_error is False


if __name__ == "__main__":
    test_config_error_on_401()
    test_config_error_on_invalid_ip()
    test_retry_backoff_increases()
    test_rate_limit_error_retryable()
    test_retryable_statuses()
    test_retry_after_header_seconds()
    test_not_found_not_retryable()
    print("OK")
