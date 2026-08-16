"""Transcode bulky replay uploads to 1080p/30fps H.264. No OpenCV, no LLM."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from bot.services.ghosteek_ai.replay.models import TARGET_SHORT_SIDE
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
COMPRESS_TIMEOUT_SECONDS = 180.0
TARGET_FPS = 30


def needs_compress(size_bytes: int, width: int, height: int, fps: float | None) -> bool:
    if size_bytes > COMPRESS_IF_OVER_BYTES:
        return True
    if size_bytes < MIN_COMPRESS_BYTES:
        return False
    if min(max(1, width), max(1, height)) > TARGET_SHORT_SIDE:
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
    """Return a working copy. On compress failure keep the original (analysis can continue)."""
    if not needs_compress(size_bytes, width, height, fps):
        return src
    out_w, out_h = scaled_dimensions(width, height)
    try:
        dest = _transcode(src, out_w, out_h)
    except ReplayError as exc:
        logger.warning("replay compress skipped (%s), using original upload", exc.code)
        return src
    try:
        out_size = dest.stat().st_size
        if out_size <= 0 or out_size >= size_bytes:
            dest.unlink(missing_ok=True)
            return src
    except OSError:
        dest.unlink(missing_ok=True)
        logger.warning("replay compress output unreadable, using original upload")
        return src
    logger.info(
        "replay compressed %s -> %s bytes (%sx%s)",
        size_bytes,
        out_size,
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

    # Prefer fps cap; fall back to scale-only if the filter graph fails on odd inputs.
    attempts = (
        f"scale={width}:{height}:flags=lanczos,fps={TARGET_FPS}",
        f"scale={width}:{height}:flags=lanczos",
    )
    last_err = b""
    for vf in attempts:
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

        if completed.returncode == 0 and dest.is_file() and dest.stat().st_size > 0:
            return dest
        last_err = (completed.stderr or b"").strip() or (completed.stdout or b"").strip()
        dest.unlink(missing_ok=True)

    if last_err:
        logger.warning("ffmpeg compress failed: %s", last_err.decode("utf-8", errors="replace")[:500])
    raise ReplayError(CODE_COMPRESS_FAILED)


def _subprocess_kwargs() -> dict:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
