"""Tests for Clash Royale API client helpers."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from bot.services.clash_api import (
    ClashRoyaleClient,
    ClashRoyaleAPIError,
    _config_error_message,
    _is_retryable_http_status,
    _parse_retry_after_header,
    _retry_delay_seconds,
    _safe_api_path,
)


async def _run_clan_endpoint_shapes() -> None:
    client = object.__new__(ClashRoyaleClient)
    paths: list[str] = []

    async def fake_request(path: str):
        paths.append(path)
        if path.endswith("/members"):
            return {"items": [{"tag": "#A", "name": "Alpha"}]}
        return {"tag": "#CLAN", "name": "Ghosteek"}

    client._request = fake_request
    assert (await client.get_clan("CLAN"))["name"] == "Ghosteek"
    assert (await client.get_clan_members("#CLAN"))[0]["name"] == "Alpha"
    assert paths == ["/clans/%23CLAN", "/clans/%23CLAN/members"]


def test_clan_endpoint_shapes() -> None:
    asyncio.run(_run_clan_endpoint_shapes())


def test_player_logging_does_not_change_request_or_result(caplog) -> None:
    client = object.__new__(ClashRoyaleClient)
    data = {"tag": "#P0YQ88", "name": "Fixture Personal Name"}
    paths = []

    async def fake_request(path):
        paths.append(path)
        return data

    client._request = fake_request
    with caplog.at_level(logging.DEBUG, logger="bot.services.clash_api"):
        result = asyncio.run(client.get_player("#P0YQ88"))
    assert result is data
    assert paths == ["/players/%23P0YQ88"]
    assert "CR API player fetched" in caplog.text
    assert "P0YQ88" not in caplog.text
    assert "Fixture Personal Name" not in caplog.text
    assert _safe_api_path(paths[0] + "/battlelog?token=private") == "/players/{tag}/battlelog"


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
