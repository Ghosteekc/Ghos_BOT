"""Tests for Clash Royale API client helpers."""

from __future__ import annotations

from bot.services.clash_api import ClashRoyaleAPIError, _config_error_message, _retry_delay_seconds


def test_config_error_on_401() -> None:
    err = _config_error_message(401, '{"reason":"accessDenied"}')
    assert err.config_error is True
    assert err.status == 401


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
