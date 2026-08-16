"""Stage 3 FrameSampler: timestamps, downscale, cleanup, adjacent dedupe. No real video files."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from bot.services.ghosteek_ai.replay.facts import ReplayFactsBuilder
from bot.services.ghosteek_ai.replay.models import (
    ReplayDetection,
    sample_frame_count,
)
from bot.services.ghosteek_ai.replay.sampler import (
    FrameSampler,
    hamming_distance,
    is_adjacent_near_duplicate,
    min_kept_frames_for_plan,
    scaled_dimensions,
    should_skip_adjacent_duplicate,
    timestamps_at_fps,
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


def test_identical_frames_keep_coverage_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Identical adjacent hashes must not collapse to 1 frame or hard-fail the upload."""
    sampler = FrameSampler(count=16, timeout_seconds=20.0, dedupe=True, adaptive=False)

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
    assert len(frames) >= min_kept_frames_for_plan(16)
    assert len(frames) != 1
    stamps = [f.timestamp for f in frames]
    assert stamps == sorted(stamps)
    assert stamps[0] == 0.0


def test_cr_hud_near_dup_sequence_keeps_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """All adjacent digests within skip threshold still keep first/last + coverage stride."""
    # Hamming distance 1 between consecutive → would skip without coverage guards.
    call = {"i": 0}

    def fake_extract(self, *, binary, video_path, timestamp, dest, width, height, timeout):
        del self, binary, video_path, timeout
        Image.new("RGB", (width, height), (20, 30, 40)).save(dest, "JPEG")

    def fake_hash(path: Path) -> int:
        del path
        i = call["i"]
        call["i"] += 1
        return i  # consecutive Hamming == 1

    sampler = FrameSampler(
        adaptive=True,
        analysis_fps_value=3.0,
        event_fps_value=8.0,
        max_frames=96,
        timeout_seconds=60.0,
        dedupe=True,
    )
    monkeypatch.setattr(FrameSampler, "_extract_one", fake_extract)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.average_hash", fake_hash)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: "ffmpeg")
    frames = list(
        sampler.iter_sampled_frames(
            Path("cr.mp4"),
            duration=45.0,
            src_width=720,
            src_height=1560,
        )
    )
    assert len(frames) >= 8
    assert len(frames) != 1
    stamps = [f.timestamp for f in frames]
    assert stamps == sorted(stamps)
    assert stamps[0] == 0.0
    assert stamps[-1] >= 45.0 * 0.85


def test_adjacent_only_dedupe_preserves_non_neighbors(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A, ~A, B, ~A:
    - second may drop as adjacent dup of A
    - fourth must NOT drop just because it resembles frame0
    """
    # Hamming(A,~A)=1 <= 6; Hamming(A,B) and (~A,B) >> 6; Hamming(B,~A)>>6
    digests = [0x0000, 0x0001, 0x0FFF_FFFF_FFFF_FFFF, 0x0002]
    assert is_adjacent_near_duplicate(digests[1], digests[0])
    assert not is_adjacent_near_duplicate(digests[2], digests[0])
    assert not is_adjacent_near_duplicate(digests[3], digests[2])
    assert hamming_distance(digests[3], digests[0]) <= 6  # similar to A historically

    call = {"i": 0}

    def fake_extract(self, *, binary, video_path, timestamp, dest, width, height, timeout):
        del self, binary, video_path, timestamp, timeout
        Image.new("RGB", (width, height), (10, 10, 10)).save(dest, "JPEG")

    def fake_hash(path: Path) -> int:
        del path
        idx = min(call["i"], len(digests) - 1)
        call["i"] += 1
        return digests[idx]

    sampler = FrameSampler(count=4, timeout_seconds=20.0, dedupe=True, adaptive=False)
    monkeypatch.setattr(FrameSampler, "_extract_one", fake_extract)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.average_hash", fake_hash)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: "ffmpeg")
    # count=4 → planned 4 → min_keep = max(1, 4//2)=2; we keep 3 (A,B,~A)
    frames = list(
        sampler.iter_sampled_frames(
            Path("x.mp4"),
            duration=12.0,
            src_width=640,
            src_height=360,
        )
    )
    assert len(frames) == 3
    stamps = [f.timestamp for f in frames]
    assert stamps == sorted(stamps)


def test_cr_like_replay_does_not_collapse_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Similar HUD chrome but changing arena content → adjacent hashes differ enough."""
    call = {"i": 0}

    def fake_extract(self, *, binary, video_path, timestamp, dest, width, height, timeout):
        del self, binary, video_path, timeout
        # Shared dark HUD chrome + shifting arena block (tone from timestamp).
        im = Image.new("RGB", (width, height), (18, 24, 40))
        draw = ImageDraw.Draw(im)
        draw.rectangle([0, int(height * 0.82), width, height], fill=(30, 36, 52))  # card bar
        draw.rectangle([0, 0, width, int(height * 0.08)], fill=(22, 28, 44))  # top HUD
        tone = int(timestamp * 40) % 180
        draw.rectangle(
            [int(width * 0.15), int(height * 0.2), int(width * 0.85), int(height * 0.75)],
            fill=(40 + tone // 2, 90 + (tone % 50), 50 + (tone % 70)),
        )
        im.save(dest, "JPEG", quality=85)

    def fake_hash(path: Path) -> int:
        # Deterministic adjacent-differing digests; may resemble older frames.
        del path
        i = call["i"]
        call["i"] += 1
        return (i * 0x1111_1111_1111_1111) & 0xFFFF_FFFF_FFFF_FFFF

    sampler = FrameSampler(count=20, timeout_seconds=30.0, dedupe=True, adaptive=False)
    monkeypatch.setattr(FrameSampler, "_extract_one", fake_extract)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.average_hash", fake_hash)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: "ffmpeg")
    frames = list(
        sampler.iter_sampled_frames(
            Path("cr.mp4"),
            duration=45.0,
            src_width=1080,
            src_height=1920,
        )
    )
    assert len(frames) >= 8
    assert len(frames) <= 24
    stamps = [f.timestamp for f in frames]
    assert stamps == sorted(stamps)
    assert stamps[0] == 0.0
    assert stamps[-1] >= 45.0 * 0.9


def test_adaptive_dedupe_45s_not_one_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    call = {"i": 0}

    def fake_extract(self, *, binary, video_path, timestamp, dest, width, height, timeout):
        del self, binary, video_path, timeout
        _write_jpeg(Path(dest), width, height, int(timestamp * 23) + 11)

    def fake_hash(path: Path) -> int:
        name = Path(path).name
        # Probe + final extract both need adjacent variety (Hamming >> 6).
        if name.startswith("probe_"):
            idx = int(name.split("_")[1].split(".")[0])
        else:
            idx = int(name.split("_")[1].split(".")[0])
        call["i"] += 1
        # Consecutive digests differ by many bits; patterns can still revisit older ones.
        return (idx * 0x1111_1111_1111_1111) & 0xFFFF_FFFF_FFFF_FFFF

    sampler = FrameSampler(
        adaptive=True,
        analysis_fps_value=3.0,
        event_fps_value=8.0,
        max_frames=96,
        timeout_seconds=60.0,
        dedupe=True,
    )
    monkeypatch.setattr(FrameSampler, "_extract_one", fake_extract)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.average_hash", fake_hash)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: "ffmpeg")
    frames = list(
        sampler.iter_sampled_frames(
            Path("adaptive.mp4"),
            duration=45.0,
            src_width=1080,
            src_height=1920,
        )
    )
    assert len(frames) != 1
    assert len(frames) >= min_kept_frames_for_plan(
        len(timestamps_at_fps(45.0, 3.0, max_frames=96))
    )
    assert len(frames) <= 96
    stamps = [f.timestamp for f in frames]
    assert stamps == sorted(stamps)
    assert stamps[0] == 0.0
    assert stamps[-1] >= 45.0 * 0.85


def test_sorted_timestamps_cover_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    frames, _ = _run_sampler(monkeypatch, 45.0, 1920, 1080, 20)
    stamps = [f.timestamp for f in frames]
    assert stamps == sorted(stamps)
    assert stamps[0] == 0.0
    assert stamps[-1] >= 45.0 * 0.9


def test_frames_analyzed_detection_and_facts_agree() -> None:
    detection = ReplayDetection(status="cr_replay", confidence=0.83, frames_analyzed=20)
    result = ReplayFactsBuilder().build(detection, [], duration_seconds=45.0)
    assert result is not None
    assert result.frames_analyzed == detection.frames_analyzed
    assert result.to_dict()["frames_analyzed"] == detection.to_dict()["frames_analyzed"]


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

    def raise_timeout(self, **kwargs):
        del self, kwargs
        raise ReplayError(CODE_ANALYSIS_TIMEOUT)

    monkeypatch.setattr(FrameSampler, "_extract_one", raise_timeout)
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.sampler.find_ffmpeg", lambda: "ffmpeg")
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
