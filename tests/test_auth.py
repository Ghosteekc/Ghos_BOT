"""Tests for Telegram initData validation."""

from __future__ import annotations

import pytest

from bot.api.auth import InitDataError, validate_auth_date


def test_auth_date_required() -> None:
    with pytest.raises(InitDataError):
        validate_auth_date(0, max_age_seconds=3600, now=1_700_000_000)


def test_auth_date_expired() -> None:
    now = 1_700_000_000
    with pytest.raises(InitDataError):
        validate_auth_date(now - 7200, max_age_seconds=3600, now=now)


def test_auth_date_future() -> None:
    now = 1_700_000_000
    with pytest.raises(InitDataError):
        validate_auth_date(now + 120, max_age_seconds=3600, clock_skew_seconds=60, now=now)


def test_auth_date_ok() -> None:
    now = 1_700_000_000
    validate_auth_date(now - 60, max_age_seconds=3600, now=now)
