"""Uniform + adaptive temporal frame sampling via system FFmpeg. No OpenCV, no LLM."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

from PIL import Image

from bot.services.ghosteek_ai.replay.models import (
    CHANGE_HASH_HAMMING,
    SAMPLE_FRAMES_MIN,
    TARGET_SHORT_SIDE,
    SampledFrame,
    adaptive_sampling_enabled,
    analysis_fps,
    event_fps,
    frame_timeout_seconds,
    max_analysis_frames,
    sample_frame_count,
    vision_short_side,
)
from bot.services.ghosteek_ai.replay.validator import (
    CODE_ANALYSIS_TIMEOUT,
    CODE_FFMPEG_UNAVAILABLE,
    CODE_FRAME_EXTRACTION_FAILED,
    ReplayError,
    find_ffmpeg,
)

logger = logging.getLogger(__name__)

_PER_FRAME_TIMEOUT = 8.0
_END_EPS = 0.04
# Soft floor after adjacent dedupe for a normal sampling plan (~20/96 stamps).
_MIN_KEPT_AFTER_DEDUPE = max(8, SAMPLE_FRAMES_MIN // 2)
# aHash is coarse on CR HUD chrome: only skip near-exact adjacent clones.
# Full NEAR_DUP_HAMMING=6 collapses almost every CR adjacent pair → 1 frame.
_ADJACENT_SKIP_HAMMING = 2


def timestamps_for_duration(duration: float, count: int) -> list[float]:
    """Even coverage including first and last usable timestamps."""
    n = max(2, int(count))
    safe = max(0.05, float(duration) - _END_EPS) if duration > 0.1 else max(0.0, float(duration))
    if duration <= 0:
        return [0.0] * n
    if n == 1:
        return [0.0]
    span = max(0.0, safe)
    stamps = [round(span * i / (n - 1), 4) for i in range(n)]
    stamps[0] = 0.0
    stamps[-1] = round(span, 4)
    out: list[float] = []
    for ts in stamps:
        if not out or ts > out[-1]:
            out.append(ts)
    if out[0] != 0.0:
        out.insert(0, 0.0)
    while len(out) < n:
        out.append(out[-1])
    return out[:n]


def timestamps_at_fps(duration: float, fps: float, *, max_frames: int) -> list[float]:
    """Regular grid at ~fps across duration, capped by max_frames."""
    dur = max(0.0, float(duration))
    rate = max(0.1, float(fps))
    if dur <= 0:
        return [0.0]
    step = 1.0 / rate
    stamps = [0.0]
    t = step
    end = max(0.0, dur - _END_EPS)
    while t < end - 1e-6 and len(stamps) < max_frames - 1:
        stamps.append(round(t, 4))
        t += step
    if end > stamps[-1] + 0.02 and len(stamps) < max_frames:
        stamps.append(round(end, 4))
    return _unique_sorted(stamps)[:max_frames]


def densify_on_changes(
    coarse: list[float],
    change_after_index: set[int],
    *,
    duration: float,
    event_fps: float,
    max_frames: int,
) -> list[float]:
    """
    Insert denser stamps between coarse[i] and coarse[i+1] when change_after_index contains i.
    """
    if not coarse:
        return [0.0]
    rate = max(0.1, float(event_fps))
    step = 1.0 / rate
    end = max(0.0, float(duration) - _END_EPS)
    out = list(coarse)
    for i in sorted(change_after_index):
        if i < 0 or i >= len(coarse) - 1:
            continue
        a = coarse[i]
        b = coarse[i + 1]
        t = a + step
        while t < b - 1e-4:
            out.append(round(min(t, end), 4))
            t += step
    merged = _unique_sorted(out)
    if len(merged) <= max_frames:
        return merged
    # Prefer keeping change densification: keep first/last + evenly thin
    return timestamps_for_duration(duration, max_frames)


def scaled_dimensions(width: int, height: int, short_side: int = TARGET_SHORT_SIDE) -> tuple[int, int]:
    """Downscale so the shorter side is ~1080px. Do not upscale. Keep aspect ratio."""
    w = max(1, int(width))
    h = max(1, int(height))
    shortest = min(w, h)
    if shortest <= short_side:
        return _even(w), _even(h)
    scale = short_side / shortest
    return _even(max(2, round(w * scale))), _even(max(2, round(h * scale)))


def _even(value: int) -> int:
    return value if value % 2 == 0 else max(2, value - 1)


def _unique_sorted(stamps: list[float]) -> list[float]:
    out: list[float] = []
    for ts in sorted(stamps):
        if not out or ts - out[-1] >= 0.02:
            out.append(round(ts, 4))
    return out


def average_hash(path: Path) -> int:
    with Image.open(path) as raw:
        small = raw.convert("L").resize((8, 8), Image.BILINEAR)
        pixels = list(small.get_flattened_data())
    avg = sum(pixels) / max(len(pixels), 1)
    bits = 0
    for pixel in pixels:
        bits = (bits << 1) | (1 if pixel >= avg else 0)
    return bits


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def min_kept_frames_for_plan(planned: int) -> int:
    """Minimum accepted frames after adjacent dedupe for a sampling plan."""
    n = max(0, int(planned))
    if n <= 1:
        return 1
    if n < _MIN_KEPT_AFTER_DEDUPE:
        return max(1, n // 2)
    return _MIN_KEPT_AFTER_DEDUPE


def is_adjacent_near_duplicate(
    digest: int,
    previous_digest: int | None,
    *,
    threshold: int = _ADJACENT_SKIP_HAMMING,
) -> bool:
    """True only when digest is near-identical to the immediately previous accepted frame."""
    if previous_digest is None:
        return False
    return hamming_distance(digest, previous_digest) <= threshold


def should_skip_adjacent_duplicate(
    *,
    is_duplicate: bool,
    index: int,
    planned: int,
    produced: int,
    min_keep: int,
) -> bool:
    """
    Skip adjacent near-dups only when temporal coverage can still be met.

    Always keep first/last and evenly spaced coverage stamps so CR HUD-like
    sequences do not collapse to a single frame.
    """
    if not is_duplicate:
        return False
    n = max(1, int(planned))
    i = max(0, int(index))
    kept = max(0, int(produced))
    floor = max(1, int(min_keep))
    if i <= 0 or i >= n - 1:
        return False
    stride = max(1, n // floor)
    if i % stride == 0:
        return False
    # If skipping would make min_keep unreachable, force-keep.
    max_if_skip = kept + (n - i - 1)
    if max_if_skip < floor:
        return False
    return True


class FrameSampler:
    """
    Extract analysis frames at ~1080p.

    - Uniform mode (explicit count / adaptive off): Stage 2–4 compatible 16–24 grid.
    - Adaptive mode: ~analysis_fps baseline, densify to ~event_fps on visual change.
    """

    def __init__(
        self,
        *,
        count: int | None = None,
        timeout_seconds: float | None = None,
        dedupe: bool = True,
        adaptive: bool | None = None,
        analysis_fps_value: float | None = None,
        event_fps_value: float | None = None,
        max_frames: int | None = None,
    ) -> None:
        self._explicit_count = count
        self.count = count if count is not None else sample_frame_count()
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else frame_timeout_seconds()
        self.dedupe = dedupe
        if adaptive is None:
            self.adaptive = count is None and adaptive_sampling_enabled()
        else:
            self.adaptive = bool(adaptive)
        self.analysis_fps = (
            float(analysis_fps_value) if analysis_fps_value is not None else analysis_fps()
        )
        self.event_fps = float(event_fps_value) if event_fps_value is not None else event_fps()
        self.max_frames = int(max_frames) if max_frames is not None else max_analysis_frames()

    def iter_sampled_frames(
        self,
        video_path: Path,
        *,
        duration: float,
        src_width: int,
        src_height: int,
    ) -> Iterator[SampledFrame]:
        binary = find_ffmpeg()
        if not binary:
            raise ReplayError(CODE_FFMPEG_UNAVAILABLE)

        out_w, out_h = scaled_dimensions(src_width, src_height)
        tmpdir = Path(tempfile.mkdtemp(prefix="ghosteek-replay-frames-"))
        deadline = time.monotonic() + self.timeout_seconds
        produced = 0
        try:
            if self.adaptive:
                stamps = self._plan_adaptive_stamps(
                    binary=binary,
                    video_path=video_path,
                    duration=duration,
                    width=out_w,
                    height=out_h,
                    tmpdir=tmpdir,
                    deadline=deadline,
                )
            else:
                stamps = timestamps_for_duration(duration, self.count)

            last_hash: int | None = None
            min_keep = min_kept_frames_for_plan(len(stamps))
            for index, ts in enumerate(stamps):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReplayError(CODE_ANALYSIS_TIMEOUT)
                dest = tmpdir / f"frame_{index:03d}.jpg"
                try:
                    self._extract_one(
                        binary=binary,
                        video_path=video_path,
                        timestamp=ts,
                        dest=dest,
                        width=out_w,
                        height=out_h,
                        timeout=min(_PER_FRAME_TIMEOUT, remaining),
                    )
                    digest = average_hash(dest)
                    # Adjacent-only: never compare against the full history (CR HUD collapse).
                    is_dup = self.dedupe and is_adjacent_near_duplicate(digest, last_hash)
                    if should_skip_adjacent_duplicate(
                        is_duplicate=is_dup,
                        index=index,
                        planned=len(stamps),
                        produced=produced,
                        min_keep=min_keep,
                    ):
                        dest.unlink(missing_ok=True)
                        continue
                    last_hash = digest
                    produced += 1
                    try:
                        yield SampledFrame(
                            path=str(dest),
                            timestamp=ts,
                            width=out_w,
                            height=out_h,
                        )
                    finally:
                        dest.unlink(missing_ok=True)
                except ReplayError:
                    dest.unlink(missing_ok=True)
                    raise
                except subprocess.TimeoutExpired:
                    dest.unlink(missing_ok=True)
                    raise ReplayError(CODE_ANALYSIS_TIMEOUT) from None
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        if produced == 0:
            raise ReplayError(CODE_FRAME_EXTRACTION_FAILED)
        if produced < min_keep:
            # Should be rare after coverage force-keep; still block silent 1-frame success.
            logger.warning(
                "replay sampler collapse: kept %s of %s planned (min %s)",
                produced,
                len(stamps),
                min_keep,
            )
            raise ReplayError(CODE_FRAME_EXTRACTION_FAILED)

    def extract_persisted_frames(
        self,
        video_path: Path,
        *,
        timestamps: list[float],
        duration: float,
        src_width: int,
        src_height: int,
        short_side: int | None = None,
    ) -> tuple[list[SampledFrame], Path]:
        """Extract specific timestamps; caller must delete returned tmpdir."""
        binary = find_ffmpeg()
        if not binary:
            raise ReplayError(CODE_FFMPEG_UNAVAILABLE)

        out_w, out_h = scaled_dimensions(
            src_width,
            src_height,
            short_side=short_side if short_side is not None else vision_short_side(),
        )
        tmpdir = Path(tempfile.mkdtemp(prefix="ghosteek-replay-vision-"))
        deadline = time.monotonic() + self.timeout_seconds
        frames: list[SampledFrame] = []
        try:
            for index, ts in enumerate(timestamps):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReplayError(CODE_ANALYSIS_TIMEOUT)
                dest = tmpdir / f"vision_{index:03d}.jpg"
                self._extract_one(
                    binary=binary,
                    video_path=video_path,
                    timestamp=ts,
                    dest=dest,
                    width=out_w,
                    height=out_h,
                    timeout=min(_PER_FRAME_TIMEOUT, remaining),
                )
                frames.append(
                    SampledFrame(
                        path=str(dest),
                        timestamp=ts,
                        width=out_w,
                        height=out_h,
                    )
                )
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise

        if not frames:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise ReplayError(CODE_FRAME_EXTRACTION_FAILED)
        return frames, tmpdir

    def _plan_adaptive_stamps(
        self,
        *,
        binary: str,
        video_path: Path,
        duration: float,
        width: int,
        height: int,
        tmpdir: Path,
        deadline: float,
    ) -> list[float]:
        coarse = timestamps_at_fps(
            duration,
            self.analysis_fps,
            max_frames=min(self.max_frames, max(8, int(duration * self.analysis_fps) + 2)),
        )
        hashes: list[int] = []
        for i, ts in enumerate(coarse):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReplayError(CODE_ANALYSIS_TIMEOUT)
            dest = tmpdir / f"probe_{i:03d}.jpg"
            try:
                self._extract_one(
                    binary=binary,
                    video_path=video_path,
                    timestamp=ts,
                    dest=dest,
                    width=width,
                    height=height,
                    timeout=min(_PER_FRAME_TIMEOUT, remaining),
                )
                hashes.append(average_hash(dest))
            finally:
                dest.unlink(missing_ok=True)

        change_after: set[int] = set()
        for i in range(len(hashes) - 1):
            if hamming_distance(hashes[i], hashes[i + 1]) >= CHANGE_HASH_HAMMING:
                change_after.add(i)

        return densify_on_changes(
            coarse,
            change_after,
            duration=duration,
            event_fps=self.event_fps,
            max_frames=self.max_frames,
        )

    def _extract_one(
        self,
        *,
        binary: str,
        video_path: Path,
        timestamp: float,
        dest: Path,
        width: int,
        height: int,
        timeout: float,
    ) -> None:
        vf = f"scale={width}:{height}:flags=lanczos"
        cmd = [
            binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            vf,
            "-q:v",
            "3",
            "-y",
            str(dest),
        ]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                timeout=max(1.0, timeout),
                check=False,
                **_subprocess_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise ReplayError(CODE_ANALYSIS_TIMEOUT) from exc
        except OSError as exc:
            raise ReplayError(CODE_FRAME_EXTRACTION_FAILED) from exc

        if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
            raise ReplayError(CODE_FRAME_EXTRACTION_FAILED)


def _subprocess_kwargs() -> dict:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
