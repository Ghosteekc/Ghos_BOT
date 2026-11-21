"""Privacy checks use only synthetic data and mocked external services."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bot.api.routes import profile
from bot.services.clash_api import ClashRoyaleAPIError


def test_profile_failure_does_not_log_player_tag_or_upstream_response():
    tag = "#P0YQ88"
    private = "fixture-private-upstream-value"
    user = SimpleNamespace(player_tag=tag, player_name="fixture", trophies=100, arena_id=None)
    client = SimpleNamespace(
        get_player=AsyncMock(side_effect=ClashRoyaleAPIError(private, status=503)),
        close=AsyncMock(),
    )
    with (
        patch.object(profile, "ClashRoyaleClient", return_value=client),
        patch.object(profile, "get_subscription_info", AsyncMock(return_value={"active": False})),
        patch.object(profile, "get_cached_stats", AsyncMock(return_value=None)),
        patch.object(profile, "_daily_trophy_for_user", AsyncMock(return_value=None)),
        patch.object(profile, "logger") as logger,
    ):
        # All awaited dependencies are immediate mocks: no event-loop sockets needed.
        with pytest.raises(StopIteration) as completed:
            profile.get_profile(user=user, session=None).send(None)
        result = completed.value.value
    assert result.player_tag == tag
    client.close.assert_awaited_once()
    args = logger.warning.call_args.args
    assert tag not in repr(args)
    assert private not in repr(args)
    assert args[-1] == 503


def test_exception_handler_logs_route_template_not_request_path():
    from fastapi import FastAPI
    from bot.api.errors import register_exception_handlers
    from bot.api import errors

    app = FastAPI()
    register_exception_handlers(app)
    request = SimpleNamespace(
        method="GET", url=SimpleNamespace(path="/api/users/private-fixture"),
        scope={"route": SimpleNamespace(path="/api/users/{user_id}")},
    )
    with patch.object(errors, "logger") as logger:
        with pytest.raises(StopIteration) as completed:
            app.exception_handlers[Exception](request, RuntimeError("private-fixture")).send(None)
    assert completed.value.value.status_code == 500
    args = logger.exception.call_args.args
    assert "/api/users/{user_id}" in args
    assert "private-fixture" not in repr(args)
