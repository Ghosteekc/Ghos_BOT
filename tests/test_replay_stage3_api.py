"""Stage 3 API: cr / not_cr / uncertain, Stage 2 errors still work, /ask untouched."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.responses import JSONResponse

from bot.api.routes import ai as ai_routes
from bot.api.schemas import GhosteekAiAskRequest
from bot.services.ghosteek_ai.models import GhosteekAiResponse
from bot.services.ghosteek_ai.replay.models import DetectionBundle, ReplayDetection
from bot.services.ghosteek_ai.replay.service import ReplayAnalyzeService
from bot.services.ghosteek_ai.replay.validator import CODE_INVALID_FORMAT

MP4_HEADER = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def _ok_probe(_path: Path) -> tuple[float, int, int, float | None]:
    return 187.4, 1920, 1080, 60.0


def _fake_upload(filename: str, data: bytes, content_type: str | None) -> SimpleNamespace:
    state = {"off": 0}

    async def read(n: int = -1) -> bytes:
        off = state["off"]
        if n is None or n < 0:
            chunk = data[off:]
        else:
            chunk = data[off : off + n]
        state["off"] = off + len(chunk)
        return chunk

    async def close() -> None:
        return None

    return SimpleNamespace(filename=filename, content_type=content_type, read=read, close=close)


def _call_analyze(monkeypatch, detection: ReplayDetection, filename: str = "battle.mp4"):
    service = ReplayAnalyzeService()
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.service.probe_video", _ok_probe)
    monkeypatch.setattr(
        ReplayAnalyzeService,
        "_run_detection",
        lambda self, *args, **kwargs: DetectionBundle(detection=detection, frames=()),
    )
    monkeypatch.setattr(ai_routes, "get_replay_service", lambda: service)

    async def _run():
        return await ai_routes.analyze_replay(
            user=MagicMock(),
            file=_fake_upload(filename, MP4_HEADER, "video/mp4"),  # type: ignore[arg-type]
        )

    return asyncio.run(_run())


def test_api_cr_like_status(monkeypatch) -> None:
    result = _call_analyze(
        monkeypatch,
        ReplayDetection(status="cr_replay", confidence=0.91, frames_analyzed=20, observations=["card bar detected"]),
    )
    payload = result.model_dump()
    assert payload["ok"] is True
    assert payload["status"] == "cr_replay"
    assert payload["replay_detection"]["status"] == "cr_replay"
    assert payload["replay_detection"]["confidence"] == 0.91
    assert payload["replay_detection"]["frames_analyzed"] == 20


def test_api_not_cr_status(monkeypatch) -> None:
    result = _call_analyze(
        monkeypatch,
        ReplayDetection(
            status="not_cr_replay",
            confidence=0.12,
            frames_analyzed=20,
            observations=["Clash Royale HUD signals not detected"],
        ),
        filename="clash_royale_win.mp4",
    )
    payload = result.model_dump()
    assert payload["ok"] is True
    assert payload["status"] == "not_cr_replay"
    assert payload["filename"] == "clash_royale_win.mp4"
    assert payload["replay_detection"]["status"] == "not_cr_replay"


def test_api_uncertain_status(monkeypatch) -> None:
    result = _call_analyze(
        monkeypatch,
        ReplayDetection(
            status="uncertain",
            confidence=0.48,
            frames_analyzed=20,
            observations=["insufficient Clash Royale-specific signals"],
        ),
    )
    payload = result.model_dump()
    assert payload["ok"] is True
    assert payload["status"] == "uncertain"
    assert payload["replay_detection"]["confidence"] == 0.48


def test_stage2_validation_errors_still_work(monkeypatch) -> None:
    service = ReplayAnalyzeService()
    monkeypatch.setattr(ai_routes, "get_replay_service", lambda: service)

    async def _run():
        return await ai_routes.analyze_replay(
            user=MagicMock(),
            file=_fake_upload("photo.png", PNG_BYTES, "image/png"),  # type: ignore[arg-type]
        )

    response = asyncio.run(_run())
    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    body = response.body
    if isinstance(body, memoryview):
        body = body.tobytes()
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    assert CODE_INVALID_FORMAT in text
    assert "traceback" not in text.lower()


def test_ask_ai_unaffected(monkeypatch) -> None:
    async def _fake_ask(message: str, user, context=None):
        del user, context
        return GhosteekAiResponse(intent="chat", answer=f"echo:{message}")

    monkeypatch.setattr(ai_routes, "ask_ghosteek_ai", _fake_ask)

    async def _run():
        return await ai_routes.ask_ai(GhosteekAiAskRequest(message="колода"), user=MagicMock())

    result = asyncio.run(_run())
    assert result.intent == "chat"
    assert result.answer == "echo:колода"
