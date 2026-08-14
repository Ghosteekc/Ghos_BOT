"""Stage 3 FrameSampler: timestamps, downscale, cleanup, errors. No real video files."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from bot.services.ghosteek_ai.replay.models import sample_frame_count
from bot.services.ghosteek_ai.replay.sampler import (
    FrameSampler,
    scaled_dimensions,
    timestamps_for_duration,
)
from bot.services.ghosteek_ai.replay.validator import (
    CODE_ANALYSIS_TIMEOUT,
    CODE_FFMPEG_UNAVAILABLE,
    CODE_FRAME_EXTRACTION_FAILED,
    ReplayError,
)


def _write_jpeg(dest: Path, width: int, height: int, tone: int) -> None:
    im = Image.new("RGB", (width, height), (12, 12, 16))
    draw = ImageDraw.Draw(im)
    cell = max(24, min(width, height) // 8)
    phase = tone % 8
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if ((x // cell) + (y // cell) + phase) % 2 == 0:
                draw.rectangle(
                    [x, y, min(width - 1, x + cell), min(height - 1, y + cell)],
                    fill=((tone * 13) % 200 + 30, (x + tone) % 180, (y + tone * 3) % 200),
                )
    im.save(dest, "JPEG", quality=85)


def test_sample_count_clamps_extreme_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_SAMPLE_FRAMES", "1000")
    assert sample_frame_count() == 24
    monkeypatch.setenv("REPLAY_SAMPLE_FRAMES", "2")
    assert sample_frame_count() == 16


def test_timestamps_30s_count_and_ends() -> None:
    stamps = timestamps_for_duration(30.0, 20)
    assert len(stamps) == 20
    assert stamps[0] == 0.0
    assert stamps[-1] >= 30.0 * 0.9
    gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
    assert max(gaps) - min(gaps) < 0.2


def test_timestamps_3min_and_8min() -> None:
    for duration in (180.0, 480.0):
        stamps = timestamps_for_duration(duration, 20)
        assert len(stamps) == 20
        assert stamps[0] == 0.0
        assert stamps[-1] >= duration * 0.9
        mid = stamps[len(stamps) // 2]
        assert duration * 0.35 < mid < duration * 0.65


def test_scaled_720p_preserves_aspect() -> None:
    w, h = scaled_dimensions(1920, 1080)
    assert (w, h) == (1280, 720)
    assert abs(w / h - 1920 / 1080) < 0.02
    pw, ph = scaled_dimensions(1080, 1920)
    assert (pw, ph) == (720, 1280)
    assert abs(pw / ph - 1080 / 1920) < 0.02
    # already small: do not upscale
    assert scaled_dimensions(640, 360)[0] <= 640


def _run_sampler(monkeypatch: pytest.MonkeyPatch, duration: float, src_w: int, src_h: int, count: int = 20):
    created: list[Path] = []
    sampler = FrameSampler(count=count, timeout_seconds=30.0, dedupe=False)

    def fake_extract(self, *, binary, video_path, timestamp, dest, width, height, timeout):
        del self, binary, video_path, timeout
        _write_jpeg(Path(dest), width, height, int(timestamp * 17) + 30)
        created.append(Path(dest))

    monkeypatch.setattr(FrameSampler, "_extract_one", fake_extract)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: "ffmpeg")
    frames = list(
        sampler.iter_sampled_frames(
            Path("fake.mp4"),
            duration=duration,
            src_width=src_w,
            src_height=src_h,
        )
    )
    return frames, created


def test_sampler_30s_frame_count(monkeypatch: pytest.MonkeyPatch) -> None:
    frames, created = _run_sampler(monkeypatch, 30.0, 1920, 1080, 20)
    assert 16 <= len(frames) <= 24
    assert len(frames) == 20
    assert frames[0].width == 1280
    assert frames[0].height == 720
    assert all(not path.exists() for path in created)


def test_sampler_3min_and_8min_count(monkeypatch: pytest.MonkeyPatch) -> None:
    for duration in (180.0, 480.0):
        frames, _created = _run_sampler(monkeypatch, duration, 1080, 1920, 20)
        assert len(frames) == 20
        assert frames[0].width == 720
        assert frames[0].height == 1280


def test_first_last_timestamps_included(monkeypatch: pytest.MonkeyPatch) -> None:
    frames, _created = _run_sampler(monkeypatch, 180.0, 1920, 1080, 20)
    assert frames[0].timestamp == 0.0
    assert frames[-1].timestamp >= 180.0 * 0.9


def test_temp_frames_deleted_after_iteration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    frames, created = _run_sampler(monkeypatch, 30.0, 1920, 1080, 16)
    assert frames
    assert created
    assert all(not path.exists() for path in created)


def test_near_duplicates_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = FrameSampler(count=16, timeout_seconds=20.0, dedupe=True)

    def same_extract(self, *, binary, video_path, timestamp, dest, width, height, timeout):
        del self, binary, video_path, timestamp, timeout
        Image.new("RGB", (width, height), (80, 40, 20)).save(dest, "JPEG")

    monkeypatch.setattr(FrameSampler, "_extract_one", same_extract)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: "ffmpeg")
    frames = list(
        sampler.iter_sampled_frames(
            Path("x.mp4"),
            duration=30.0,
            src_width=1920,
            src_height=1080,
        )
    )
    assert len(frames) == 1


def test_corrupted_video_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = FrameSampler(count=16, timeout_seconds=20.0)

    def boom(self, **kwargs):
        del self, kwargs
        raise ReplayError(CODE_FRAME_EXTRACTION_FAILED)

    monkeypatch.setattr(FrameSampler, "_extract_one", boom)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: "ffmpeg")
    with pytest.raises(ReplayError) as exc:
        list(
            sampler.iter_sampled_frames(
                Path("broken.mp4"),
                duration=30.0,
                src_width=1920,
                src_height=1080,
            )
        )
    assert exc.value.code == CODE_FRAME_EXTRACTION_FAILED


def test_ffmpeg_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: None)
    sampler = FrameSampler(count=16)
    with pytest.raises(ReplayError) as exc:
        list(
            sampler.iter_sampled_frames(
                Path("x.mp4"),
                duration=10.0,
                src_width=640,
                src_height=360,
            )
        )
    assert exc.value.code == CODE_FFMPEG_UNAVAILABLE


def test_timeout_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = FrameSampler(count=16, timeout_seconds=20.0)

    def slow(self, **kwargs):
        del self, kwargs
        raise subprocess.TimeoutExpired("ffmpeg", 8)

    monkeypatch.setattr(FrameSampler, "_extract_one", slow)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: "ffmpeg")
    # _extract_one is what maps TimeoutExpired; simulate that mapping:
    def raise_timeout(self, **kwargs):
        del self, kwargs
        raise ReplayError(CODE_ANALYSIS_TIMEOUT)

    monkeypatch.setattr(FrameSampler, "_extract_one", raise_timeout)
    with pytest.raises(ReplayError) as exc:
        list(
            sampler.iter_sampled_frames(
                Path("x.mp4"),
                duration=30.0,
                src_width=1920,
                src_height=1080,
            )
        )
    assert exc.value.code == CODE_ANALYSIS_TIMEOUT
