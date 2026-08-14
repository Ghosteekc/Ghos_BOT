"""Transcode bulky replay uploads to 720p/30fps H.264. No OpenCV, no LLM."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from bot.services.ghosteek_ai.replay.sampler import scaled_dimensions
from bot.services.ghosteek_ai.replay.validator import (
    CODE_COMPRESS_FAILED,
    CODE_FFMPEG_UNAVAILABLE,
    ReplayError,
    find_ffmpeg,
)

logger = logging.getLogger(__name__)

MIN_COMPRESS_BYTES = 512 * 1024
COMPRESS_IF_OVER_BYTES = 24 * 1024 * 1024
COMPRESS_TIMEOUT_SECONDS = 90.0
TARGET_FPS = 30


def needs_compress(size_bytes: int, width: int, height: int, fps: float | None) -> bool:
    if size_bytes > COMPRESS_IF_OVER_BYTES:
        return True
    if size_bytes < MIN_COMPRESS_BYTES:
        return False
    if min(max(1, width), max(1, height)) > 720:
        return True
    if fps is not None and fps > 32:
        return True
    return False


def compress_replay_video(
    src: Path,
    *,
    size_bytes: int,
    width: int,
    height: int,
    fps: float | None,
) -> Path:
    """Return a working copy. May be `src` when already small enough."""
    if not needs_compress(size_bytes, width, height, fps):
        return src
    out_w, out_h = scaled_dimensions(width, height)
    dest = _transcode(src, out_w, out_h)
    try:
        if dest.stat().st_size >= size_bytes:
            dest.unlink(missing_ok=True)
            return src
    except OSError:
        dest.unlink(missing_ok=True)
        raise ReplayError(CODE_COMPRESS_FAILED) from None
    logger.info(
        "replay compressed %s -> %s bytes (%sx%s)",
        size_bytes,
        dest.stat().st_size,
        out_w,
        out_h,
    )
    return dest


def _transcode(src: Path, width: int, height: int) -> Path:
    binary = find_ffmpeg()
    if not binary:
        raise ReplayError(CODE_FFMPEG_UNAVAILABLE)

    handle = tempfile.NamedTemporaryFile(prefix="ghosteek-replay-c-", suffix=".mp4", delete=False)
    dest = Path(handle.name)
    handle.close()
    vf = f"scale={width}:{height}:flags=lanczos,fps={TARGET_FPS}"
    cmd = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-an",
        "-sn",
        "-dn",
        "-map",
        "0:v:0",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            timeout=COMPRESS_TIMEOUT_SECONDS,
            check=False,
            **_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        dest.unlink(missing_ok=True)
        raise ReplayError(CODE_COMPRESS_FAILED) from exc
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise ReplayError(CODE_COMPRESS_FAILED) from exc

    if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
        dest.unlink(missing_ok=True)
        raise ReplayError(CODE_COMPRESS_FAILED)
    return dest


def _subprocess_kwargs() -> dict:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
