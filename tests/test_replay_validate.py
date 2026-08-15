"""Stage 2 replay validation: MIME/ext/size/duration, temp cleanup, busy lock, API shape."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.responses import JSONResponse

from bot.api.routes import ai as ai_routes
from bot.api.schemas import GhosteekAiAskRequest
from bot.services.ghosteek_ai.models import GhosteekAiResponse
from bot.services.ghosteek_ai.replay.models import DetectionBundle, ReplayDetection
from bot.services.ghosteek_ai.replay.service import ReplayAnalyzeService
from bot.services.ghosteek_ai.replay.validator import (
    CODE_BUSY,
    CODE_FFMPEG_UNAVAILABLE,
    CODE_INTERNAL,
    CODE_INVALID_FORMAT,
    CODE_INVALID_VIDEO,
    CODE_TOO_LARGE,
    CODE_TOO_LONG,
    ReplayError,
    parse_ffprobe_payload,
    probe_video,
)

MP4_HEADER = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32
WEBM_HEADER = b"\x1a\x45\xdf\xa3" + b"\x00" * 40
MOV_HEADER = b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 24
TEXT_BYTES = b"this is a text file, not a video\n"


def _ok_probe(_path: Path) -> tuple[float, int, int, float | None]:
    return 187.4, 1920, 1080, 60.0


def _reader(data: bytes):
    state = {"off": 0}

    async def read(n: int) -> bytes:
        off = state["off"]
        chunk = data[off : off + n]
        state["off"] = off + len(chunk)
        return chunk

    return read


async def _validate(svc: ReplayAnalyzeService, filename: str, data: bytes, content_type: str | None):
    return await svc.validate_upload(
        filename=filename,
        content_type=content_type,
        read=_reader(data),
    )


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


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> ReplayAnalyzeService:
    service = ReplayAnalyzeService()
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.service.probe_video",
        _ok_probe,
    )
    return service


def test_valid_mp4(svc: ReplayAnalyzeService) -> None:
    meta = asyncio.run(_validate(svc, "battle.mp4", MP4_HEADER, "video/mp4"))
    assert meta.filename == "battle.mp4"
    assert meta.mime_type == "video/mp4"
    assert meta.width == 1920
    assert meta.height == 1080
    assert meta.fps == 60.0
    assert meta.duration_seconds == 187.4


def test_valid_webm(svc: ReplayAnalyzeService) -> None:
    meta = asyncio.run(_validate(svc, "clip.webm", WEBM_HEADER, "video/webm"))
    assert meta.mime_type == "video/webm"
    assert meta.filename == "clip.webm"


def test_valid_mov(svc: ReplayAnalyzeService) -> None:
    meta = asyncio.run(_validate(svc, "replay.mov", MOV_HEADER, "video/quicktime"))
    assert meta.mime_type == "video/quicktime"
    assert meta.filename == "replay.mov"


def test_image_upload_rejected(svc: ReplayAnalyzeService) -> None:
    with pytest.raises(ReplayError) as exc:
        asyncio.run(_validate(svc, "photo.png", PNG_BYTES, "image/png"))
    assert exc.value.code == CODE_INVALID_FORMAT


def test_jpeg_named_as_mp4_rejected(svc: ReplayAnalyzeService) -> None:
    with pytest.raises(ReplayError) as exc:
        asyncio.run(_validate(svc, "fake.mp4", JPEG_BYTES, "video/mp4"))
    assert exc.value.code == CODE_INVALID_FORMAT


def test_text_file_rejected(svc: ReplayAnalyzeService) -> None:
    with pytest.raises(ReplayError) as exc:
        asyncio.run(_validate(svc, "notes.txt", TEXT_BYTES, "text/plain"))
    assert exc.value.code == CODE_INVALID_FORMAT


def test_file_over_80mb_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.service.MAX_SIZE_BYTES", 64)
    service = ReplayAnalyzeService()
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.service.probe_video",
        _ok_probe,
    )
    with pytest.raises(ReplayError) as exc:
        asyncio.run(_validate(service, "huge.mp4", MP4_HEADER + b"\x00" * 80, "video/mp4"))
    assert exc.value.code == CODE_TOO_LARGE


def test_video_over_8_min_rejected(svc: ReplayAnalyzeService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.service.probe_video",
        lambda _p: (8 * 60 + 1, 1920, 1080, 30.0),
    )
    with pytest.raises(ReplayError) as exc:
        asyncio.run(_validate(svc, "long.mp4", MP4_HEADER, "video/mp4"))
    assert exc.value.code == CODE_TOO_LONG


def test_parse_ffprobe_too_long() -> None:
    payload = {
        "format": {"duration": "481.0"},
        "streams": [{"codec_type": "video", "width": 1280, "height": 720, "avg_frame_rate": "30/1"}],
    }
    with pytest.raises(ReplayError) as exc:
        parse_ffprobe_payload(payload)
    assert exc.value.code == CODE_TOO_LONG


def test_corrupted_video_rejected(svc: ReplayAnalyzeService, monkeypatch: pytest.MonkeyPatch) -> None:
    def _bad(_path: Path) -> tuple[float, int, int, float | None]:
        raise ReplayError(CODE_INVALID_VIDEO)

    monkeypatch.setattr("bot.services.ghosteek_ai.replay.service.probe_video", _bad)
    with pytest.raises(ReplayError) as exc:
        asyncio.run(_validate(svc, "broken.mp4", MP4_HEADER, "video/mp4"))
    assert exc.value.code == CODE_INVALID_VIDEO


def test_ffmpeg_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.validator.find_ffprobe",
        lambda: None,
    )
    with pytest.raises(ReplayError) as exc:
        probe_video(Path("missing.mp4"))
    assert exc.value.code == CODE_FFMPEG_UNAVAILABLE


def test_ffmpeg_unavailable_via_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.validator.find_ffprobe",
        lambda: None,
    )
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.service.probe_video",
        probe_video,
    )
    service = ReplayAnalyzeService()
    with pytest.raises(ReplayError) as exc:
        asyncio.run(_validate(service, "battle.mp4", MP4_HEADER, "video/mp4"))
    assert exc.value.code == CODE_FFMPEG_UNAVAILABLE


def test_temp_file_deleted_on_success(svc: ReplayAnalyzeService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[Path] = []
    real_ntf = __import__("tempfile").NamedTemporaryFile

    def _tracking(*args, **kwargs):
        kwargs["dir"] = str(tmp_path)
        handle = real_ntf(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.service.tempfile.NamedTemporaryFile",
        _tracking,
    )
    asyncio.run(_validate(svc, "battle.mp4", MP4_HEADER, "video/mp4"))
    assert created
    assert not created[0].exists()


def test_temp_file_deleted_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[Path] = []
    real_ntf = __import__("tempfile").NamedTemporaryFile

    def _tracking(*args, **kwargs):
        kwargs["dir"] = str(tmp_path)
        handle = real_ntf(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.service.tempfile.NamedTemporaryFile",
        _tracking,
    )
    service = ReplayAnalyzeService()
    with pytest.raises(ReplayError):
        asyncio.run(_validate(service, "photo.png", PNG_BYTES, "image/png"))
    assert created
    assert not created[0].exists()


def test_concurrent_replay_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ReplayAnalyzeService()
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.service.probe_video",
        _ok_probe,
    )

    async def _run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        first_chunk_sent = False

        async def slow_read(_n: int) -> bytes:
            nonlocal first_chunk_sent
            if not first_chunk_sent:
                first_chunk_sent = True
                started.set()
                await release.wait()
                return MP4_HEADER
            return b""

        async def second_job() -> None:
            await started.wait()
            with pytest.raises(ReplayError) as exc:
                await service.validate_upload(
                    filename="other.mp4",
                    content_type="video/mp4",
                    read=_reader(MP4_HEADER),
                )
            assert exc.value.code == CODE_BUSY
            release.set()

        first = asyncio.create_task(
            service.validate_upload(
                filename="battle.mp4",
                content_type="video/mp4",
                read=slow_read,
            )
        )
        await second_job()
        meta = await first
        assert meta.filename == "battle.mp4"

    asyncio.run(_run())


def test_filename_clash_is_not_fake_cr_detection(svc: ReplayAnalyzeService) -> None:
    meta = asyncio.run(_validate(svc, "clash_royale_win.mp4", MP4_HEADER, "video/mp4"))
    assert meta.filename == "clash_royale_win.mp4"
    other = asyncio.run(_validate(svc, "random_clip.mp4", MP4_HEADER, "video/mp4"))
    assert other.filename == "random_clip.mp4"


def _error_body(response: JSONResponse) -> dict:
    raw = response.body
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if isinstance(raw, bytes):
        payload = json.loads(raw.decode("utf-8"))
    else:
        payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def test_api_internal_error_has_no_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_path: Path) -> tuple[float, int, int, float | None]:
        raise RuntimeError("SECRET_TRACEBACK_TOKEN")

    service = ReplayAnalyzeService()
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.service.probe_video", _boom)
    monkeypatch.setattr(ai_routes, "get_replay_service", lambda: service)

    async def _run():
        return await ai_routes.analyze_replay(
            user=MagicMock(),
            file=_fake_upload("battle.mp4", MP4_HEADER, "video/mp4"),  # type: ignore[arg-type]
        )

    response = asyncio.run(_run())
    assert isinstance(response, JSONResponse)
    body = _error_body(response)
    dumped = json.dumps(body)
    assert body == {"ok": False, "error_code": CODE_INTERNAL}
    assert "SECRET_TRACEBACK_TOKEN" not in dumped
    assert "traceback" not in dumped.lower()
    assert "RuntimeError" not in dumped


def test_api_busy_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ReplayAnalyzeService()
    service._busy = True
    monkeypatch.setattr(ai_routes, "get_replay_service", lambda: service)

    async def _run():
        return await ai_routes.analyze_replay(
            user=MagicMock(),
            file=_fake_upload("battle.mp4", MP4_HEADER, "video/mp4"),  # type: ignore[arg-type]
        )

    response = asyncio.run(_run())
    assert isinstance(response, JSONResponse)
    assert response.status_code == 409
    assert _error_body(response) == {"ok": False, "error_code": CODE_BUSY}


def test_api_success_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ReplayAnalyzeService()
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.service.probe_video", _ok_probe)
    monkeypatch.setattr(
        ReplayAnalyzeService,
        "_run_detection",
        lambda self, *args, **kwargs: DetectionBundle(
            detection=ReplayDetection(
                status="cr_replay",
                confidence=0.91,
                frames_analyzed=20,
                observations=["card bar detected"],
            ),
            frames=(),
        ),
    )
    monkeypatch.setattr(ai_routes, "get_replay_service", lambda: service)

    async def _run():
        return await ai_routes.analyze_replay(
            user=MagicMock(),
            file=_fake_upload("battle.mp4", MP4_HEADER, "video/mp4"),  # type: ignore[arg-type]
        )

    result = asyncio.run(_run())
    payload = result.model_dump()
    assert payload["ok"] is True
    assert payload["status"] == "cr_replay"
    assert payload["filename"] == "battle.mp4"
    assert payload["mime_type"] == "video/mp4"
    assert payload["width"] == 1920
    assert payload["height"] == 1080
    assert payload["fps"] == 60.0
    assert payload["replay_detection"]["status"] == "cr_replay"
    assert payload["replay_detection"]["frames_analyzed"] == 20
    assert "traceback" not in payload


def test_ask_ai_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_ask(message: str, user, context=None):
        del user, context
        return GhosteekAiResponse(intent="chat", answer=f"echo:{message}", sources={"ok": True})

    monkeypatch.setattr(ai_routes, "ask_ghosteek_ai", _fake_ask)
    body = GhosteekAiAskRequest(message="привет")

    async def _run():
        return await ai_routes.ask_ai(body, user=MagicMock())

    result = asyncio.run(_run())
    assert result.intent == "chat"
    assert result.answer == "echo:привет"
    assert result.deck_card is None
    assert result.battle_card is None
    assert result.analysis_card is None
