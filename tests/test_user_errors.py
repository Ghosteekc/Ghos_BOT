"""Tests for user-facing error codes."""

from bot.services.clash_api import ClashRoyaleAPIError
from bot.user_errors import code_from_clash_api, user_message


def test_user_message_contains_code() -> None:
    text = user_message("E020")
    assert "E020" in text
    assert "❌" in text


def test_clash_api_404_code() -> None:
    err = ClashRoyaleAPIError("not found", 404)
    assert code_from_clash_api(err) == "E002"


def test_clash_api_config_code() -> None:
    err = ClashRoyaleAPIError("config", 403, config_error=True)
    assert code_from_clash_api(err) == "E010"
