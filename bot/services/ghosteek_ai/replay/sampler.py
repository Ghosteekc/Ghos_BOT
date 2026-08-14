"""Uniform temporal frame sampling via system FFmpeg. No OpenCV, no LLM."""

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
    NEAR_DUP_HAMMING,
    TARGET_SHORT_SIDE,
    SampledFrame,
    frame_timeout_seconds,
    sample_frame_count,
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
    # keep unique monotonic timestamps
    out: list[float] = []
    for ts in stamps:
        if not out or ts > out[-1]:
            out.append(ts)
    if out[0] != 0.0:
        out.insert(0, 0.0)
    while len(out) < n:
        out.append(out[-1])
    return out[:n]


def scaled_dimensions(width: int, height: int, short_side: int = TARGET_SHORT_SIDE) -> tuple[int, int]:
    """Downscale so the shorter side is ~720px. Do not upscale. Keep aspect ratio."""
    w = max(1, int(width))
    h = max(1, int(height))
    shortest = min(w, h)
    if shortest <= short_side:
        return _even(w), _even(h)
    scale = short_side / shortest
    return _even(max(2, round(w * scale))), _even(max(2, round(h * scale)))


def _even(value: int) -> int:
    return value if value % 2 == 0 else max(2, value - 1)


def average_hash(path: Path) -> int:
    with Image.open(path) as raw:
        small = raw.convert("L").resize((8, 8), Image.BILINEAR)
        pixels = list(small.getdata())
    avg = sum(pixels) / max(len(pixels), 1)
    bits = 0
    for pixel in pixels:
        bits = (bits << 1) | (1 if pixel >= avg else 0)
    return bits


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class FrameSampler:
    """Extract 16–24 representative frames. Caller should analyze then discard each file."""

    def __init__(
        self,
        *,
        count: int | None = None,
        timeout_seconds: float | None = None,
        dedupe: bool = True,
    ) -> None:
        self.count = count if count is not None else sample_frame_count()
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else frame_timeout_seconds()
        self.dedupe = dedupe

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

        count = self.count
        stamps = timestamps_for_duration(duration, count)
        out_w, out_h = scaled_dimensions(src_width, src_height)
        tmpdir = Path(tempfile.mkdtemp(prefix="ghosteek-replay-frames-"))
        seen_hashes: list[int] = []
        deadline = time.monotonic() + self.timeout_seconds
        produced = 0
        try:
            for index, ts in enumerate(stamps):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReplayError(CODE_ANALYSIS_TIMEOUT)
                dest = tmpdir / f"frame_{index:02d}.jpg"
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
                    if self.dedupe and any(
                        hamming_distance(digest, prev) <= NEAR_DUP_HAMMING for prev in seen_hashes
                    ):
                        dest.unlink(missing_ok=True)
                        continue
                    seen_hashes.append(digest)
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
