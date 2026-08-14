"""Replay ingest transcode: size/resolution triggers, ffmpeg command, temp cleanup."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.responses import JSONResponse

from bot.api.routes import ai as ai_routes
from bot.services.ghosteek_ai.replay import compressor
from bot.services.ghosteek_ai.replay.compressor import compress_replay_video, needs_compress
from bot.services.ghosteek_ai.replay.service import ReplayAnalyzeService
from bot.services.ghosteek_ai.replay.validator import CODE_COMPRESS_FAILED, MAX_SIZE_BYTES, ReplayError

MP4_HEADER = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32


def test_needs_compress_skips_tiny_stub() -> None:
    assert needs_compress(50, 1920, 1080, 60.0) is False


def test_needs_compress_large_file() -> None:
    assert needs_compress(25 * 1024 * 1024, 640, 360, 24.0) is True


def test_needs_compress_1080p_real_file() -> None:
    assert needs_compress(2 * 1024 * 1024, 1920, 1080, 30.0) is True


def test_needs_compress_60fps_real_file() -> None:
    assert needs_compress(2 * 1024 * 1024, 1280, 720, 60.0) is True


def test_needs_compress_already_small_720p30() -> None:
    assert needs_compress(2 * 1024 * 1024, 1280, 720, 30.0) is False


def test_compress_skipped_returns_same_path(tmp_path: Path) -> None:
    src = tmp_path / "clip.mp4"
    src.write_bytes(MP4_HEADER)
    out = compress_replay_video(src, size_bytes=src.stat().st_size, width=1920, height=1080, fps=60.0)
    assert out == src


def test_transcode_invokes_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x" * 600_000)
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        dest = Path(cmd[-1])
        dest.write_bytes(b"c" * 1_000)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(compressor, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(compressor.subprocess, "run", fake_run)

    out = compress_replay_video(src, size_bytes=600_000, width=1920, height=1080, fps=60.0)
    assert out != src
    assert out.exists()
    cmd = captured["cmd"]
    assert "libx264" in cmd
    assert "scale=1280:720:flags=lanczos,fps=30" in cmd
    assert "-an" in cmd
    out.unlink()


def test_transcode_failure_is_compress_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x" * 600_000)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, b"", b"fail")

    monkeypatch.setattr(compressor, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(compressor.subprocess, "run", fake_run)

    with pytest.raises(ReplayError) as exc:
        compress_replay_video(src, size_bytes=600_000, width=1920, height=1080, fps=30.0)
    assert exc.value.code == CODE_COMPRESS_FAILED


def test_keeps_original_if_compress_not_smaller(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x" * 600_000)

    def fake_run(cmd, **kwargs):
        dest = Path(cmd[-1])
        dest.write_bytes(b"y" * 700_000)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(compressor, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(compressor.subprocess, "run", fake_run)

    out = compress_replay_video(src, size_bytes=600_000, width=1920, height=1080, fps=30.0)
    assert out == src


def _reader(data: bytes):
    state = {"off": 0}

    async def read(n: int) -> bytes:
        off = state["off"]
        chunk = data[off : off + n]
        state["off"] = off + len(chunk)
        return chunk

    return read


def test_pipeline_deletes_compressed_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compressed = tmp_path / "out.mp4"

    def _fake_compress(src, **kwargs):
        del src, kwargs
        compressed.write_bytes(MP4_HEADER)
        return compressed

    monkeypatch.setattr("bot.services.ghosteek_ai.replay.service.compress_replay_video", _fake_compress)
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.service.probe_video",
        lambda _p: (40.0, 1280, 720, 30.0),
    )
    service = ReplayAnalyzeService()
    asyncio.run(
        service.validate_upload(
            filename="battle.mp4",
            content_type="video/mp4",
            read=_reader(MP4_HEADER),
        )
    )
    assert not compressed.exists()


def test_upload_cap_allows_replay_over_80mb() -> None:
    assert MAX_SIZE_BYTES == 250 * 1024 * 1024


def test_api_compress_failed_status(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ReplayAnalyzeService()

    async def _boom(**kwargs):
        del kwargs
        raise ReplayError(CODE_COMPRESS_FAILED)

    monkeypatch.setattr(service, "analyze_upload", _boom)
    monkeypatch.setattr(ai_routes, "get_replay_service", lambda: service)

    upload = MagicMock()
    upload.filename = "battle.mp4"
    upload.content_type = "video/mp4"

    async def _close() -> None:
        return None

    upload.close = _close

    async def _run():
        return await ai_routes.analyze_replay(user=MagicMock(), file=upload)

    response = asyncio.run(_run())
    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    raw = response.body
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    body = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    assert body == {"ok": False, "error_code": CODE_COMPRESS_FAILED}
