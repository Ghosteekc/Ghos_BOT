"""CORS boundaries with real Telegram signature validation, no external services."""
import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends

from bot.api import app as app_module
from bot.api import deps
from bot.config import Settings, settings

ORIGIN = "https://miniapp.example.test"


class LocalClient:
    """Exercise the full ASGI middleware/router stack without optional HTTP clients."""
    def __init__(self, app):
        self.app = app

    def request(self, method, path, headers):
        async def run():
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                messages.append(message)

            await self.app({
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "scheme": "http", "path": path,
                "raw_path": path.encode(), "query_string": b"", "root_path": "",
                "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
                "server": ("testserver", 80), "client": ("127.0.0.1", 1234),
            }, receive, send)
            start = next(item for item in messages if item["type"] == "http.response.start")
            return SimpleNamespace(status_code=start["status"], headers={
                key.decode(): value.decode() for key, value in start["headers"]
            })
        return asyncio.run(run())

    def get(self, path, headers):
        return self.request("GET", path, headers)

    def options(self, path, headers):
        return self.request("OPTIONS", path, headers)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cors_allowed_origins", f"{ORIGIN},http://localhost:5173")
    monkeypatch.setattr(settings, "bot_token", "fixture-cors-token")
    monkeypatch.setattr(app_module, "WEBAPP_DIST", tmp_path / "no-dist")
    app = app_module.create_app()
    app.dependency_overrides[deps.get_db] = lambda: None
    lookup = AsyncMock(return_value=SimpleNamespace(id=1, telegram_id=42, player_tag=None))
    monkeypatch.setattr(deps.SubscriptionService, "get_or_create_user", lookup)

    @app.get("/api/cors-auth-test")
    async def auth_probe(user=Depends(deps.get_current_user)):
        return {"ok": True}

    yield LocalClient(app)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "HEAD"])
@pytest.mark.parametrize("origin", [ORIGIN, "http://localhost:5173"])
def test_allowed_preflight(client, method, origin):
    response = client.options("/api/health", headers={
        "Origin": origin, "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "content-type,x-telegram-init-data,bypass-tunnel-reminder",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in response.headers
    assert "Origin" in response.headers["vary"]


@pytest.mark.parametrize("origin,method,header", [
    ("https://untrusted.example.test", "GET", "x-telegram-init-data"),
    (ORIGIN, "PATCH", "content-type"),
    (ORIGIN, "GET", "x-unapproved-header"),
])
def test_rejected_preflight(client, origin, method, header):
    response = client.options("/api/health", headers={
        "Origin": origin, "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": header,
    })
    assert response.status_code == 400
    if origin != ORIGIN:
        assert "access-control-allow-origin" not in response.headers


def test_origin_is_not_authentication(client):
    for origin in (ORIGIN, "https://untrusted.example.test"):
        response = client.get("/api/cors-auth-test", headers={"Origin": origin})
        assert response.status_code == 401
        assert ("access-control-allow-origin" in response.headers) == (origin == ORIGIN)


def test_signed_request_and_same_origin_without_origin_header(client):
    data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 42})}
    key = hmac.new(b"WebAppData", b"fixture-cors-token", hashlib.sha256).digest()
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    data["hash"] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    for origin in (ORIGIN, None, "https://untrusted.example.test"):
        headers = {"X-Telegram-Init-Data": urlencode(data)}
        if origin:
            headers["Origin"] = origin
        response = client.get("/api/cors-auth-test", headers=headers)
        # CORS blocks browser reading, not server-side execution/authentication.
        assert response.status_code == 200
        assert ("access-control-allow-origin" in response.headers) == (origin == ORIGIN)
    data["hash"] = "invalid"
    assert client.get("/api/cors-auth-test", headers={
        "Origin": ORIGIN, "X-Telegram-Init-Data": urlencode(data),
    }).status_code == 401


def test_explicit_empty_origins_deny_cross_origin(monkeypatch):
    monkeypatch.setattr(settings, "cors_allowed_origins", "")
    client = LocalClient(app_module.create_app())
    response = client.options("/api/health", headers={
        "Origin": "https://unknown-preview.example.test",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-telegram-init-data",
    })
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("origin,allowed", [
    ("https://ghos-web2.vercel.app", True),
    ("http://localhost:5173", True),
    ("https://unknown-preview.vercel.app", False),
    ("https://ghosteekcr.loca.lt", False),
])
def test_confirmed_default_origins(monkeypatch, origin, allowed):
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    config = Settings(_env_file=None, bot_token="fixture", clash_royale_api_key="fixture")
    monkeypatch.setattr(settings, "cors_allowed_origins", config.cors_allowed_origins)
    response = LocalClient(app_module.create_app()).options("/api/health", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-telegram-init-data,bypass-tunnel-reminder",
    })
    assert response.status_code == (200 if allowed else 400)
    assert ("access-control-allow-origin" in response.headers) == allowed


@pytest.mark.parametrize("value", ["*", "null", "https://*.example.test", "https://example.test/path", "https://user:pass@example.test", "https://example.test?query=1", "https://example.test:bad"])
def test_invalid_origin_configuration(value):
    with pytest.raises(ValueError):
        Settings._validate_cors_origins(value)


def test_origin_configuration_from_environment(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", f" {ORIGIN}, http://localhost:5173,{ORIGIN} ")
    config = Settings(_env_file=None, bot_token="fixture", clash_royale_api_key="fixture")
    assert config.cors_allowed_origins == f"{ORIGIN},http://localhost:5173"
