"""Replay file validation: MIME, extension, size, magic bytes, ffprobe metadata.

Does not extract frames or inspect Clash Royale content.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Ingest cap. Phone CR recordings are transcoded after upload.
MAX_SIZE_BYTES = 250 * 1024 * 1024
MAX_DURATION_SECONDS = 8 * 60
FFPROBE_TIMEOUT_SECONDS = 20.0

ALLOWED_EXTENSIONS = frozenset({".mp4", ".webm", ".mov"})
ALLOWED_MIME_TYPES = frozenset(
    {
        "video/mp4",
        "video/webm",
        "video/quicktime",
    }
)

CODE_INVALID_FORMAT = "REPLAY_INVALID_FORMAT"
CODE_TOO_LARGE = "REPLAY_TOO_LARGE"
CODE_TOO_LONG = "REPLAY_TOO_LONG"
CODE_FFMPEG_UNAVAILABLE = "REPLAY_FFMPEG_UNAVAILABLE"
CODE_INVALID_VIDEO = "REPLAY_INVALID_VIDEO"
CODE_BUSY = "REPLAY_BUSY"
CODE_INTERNAL = "REPLAY_INTERNAL_ERROR"
CODE_FRAME_EXTRACTION_FAILED = "REPLAY_FRAME_EXTRACTION_FAILED"
CODE_FRAME_ANALYSIS_FAILED = "REPLAY_FRAME_ANALYSIS_FAILED"
CODE_ANALYSIS_TIMEOUT = "REPLAY_ANALYSIS_TIMEOUT"
CODE_COMPRESS_FAILED = "REPLAY_COMPRESS_FAILED"

_PNG = b"\x89PNG"
_JPEG = b"\xff\xd8"
_GIF = b"GIF8"
_WEBP = b"WEBP"
_EBML = b"\x1a\x45\xdf\xa3"


class ReplayError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ReplayMeta:
    filename: str
    mime_type: str
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float | None


def normalize_filename(filename: str | None) -> str:
    raw = (filename or "").strip().replace("\\", "/")
    name = Path(raw).name.strip()
    return name or "video"


def extension_of(filename: str) -> str:
    return Path(normalize_filename(filename)).suffix.lower()


def sniff_mime_from_header(header: bytes) -> str | None:
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == _WEBP:
        return "image/webp"
    if header.startswith(_PNG):
        return "image/png"
    if header.startswith(_JPEG):
        return "image/jpeg"
    if header.startswith(_GIF):
        return "image/gif"
    if header.startswith(_EBML):
        return "video/webm"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand.startswith(b"qt"):
            return "video/quicktime"
        return "video/mp4"
    return None


def resolve_mime(declared: str | None, sniffed: str | None, ext: str) -> str:
    declared_l = (declared or "").split(";")[0].strip().lower()
    if sniffed and sniffed.startswith("image/"):
        raise ReplayError(CODE_INVALID_FORMAT)
    if sniffed in ALLOWED_MIME_TYPES:
        return sniffed
    if declared_l in ALLOWED_MIME_TYPES and sniffed is None:
        # Trust declared MIME only together with a known video extension.
        if ext in ALLOWED_EXTENSIONS:
            return declared_l
        raise ReplayError(CODE_INVALID_FORMAT)
    if ext in ALLOWED_EXTENSIONS and sniffed is None and not declared_l:
        return {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mov": "video/quicktime",
        }[ext]
    raise ReplayError(CODE_INVALID_FORMAT)


def validate_identity(filename: str | None, declared_mime: str | None, header: bytes) -> tuple[str, str]:
    name = normalize_filename(filename)
    ext = extension_of(name)
    if ext not in ALLOWED_EXTENSIONS:
        raise ReplayError(CODE_INVALID_FORMAT)
    sniffed = sniff_mime_from_header(header)
    mime = resolve_mime(declared_mime, sniffed, ext)
    if mime not in ALLOWED_MIME_TYPES:
        raise ReplayError(CODE_INVALID_FORMAT)
    return name, mime


def validate_size(size_bytes: int) -> None:
    if size_bytes <= 0:
        raise ReplayError(CODE_INVALID_VIDEO)
    if size_bytes > MAX_SIZE_BYTES:
        raise ReplayError(CODE_TOO_LARGE)


def _env_binary(*names: str) -> str | None:
    for name in names:
        raw = (os.environ.get(name) or "").strip().strip('"')
        if raw and Path(raw).is_file():
            return raw
    return None


def _sibling_binary(path: str, sibling_name: str) -> str | None:
    sibling = Path(path).with_name(sibling_name)
    if sibling.is_file():
        return str(sibling)
    return None


def _common_ffmpeg_bins() -> list[Path]:
    roots: list[Path] = []
    for drive in ("G:/", "C:/", "D:/"):
        root = Path(drive)
        roots.append(root / "ffmpeg" / "bin")
        try:
            for child in root.glob("ffmpeg*/bin"):
                roots.append(child)
        except OSError:
            continue
    local = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links"
    roots.append(local)
    return roots


def find_ffprobe() -> str | None:
    env = _env_binary("REPLAY_FFPROBE", "FFPROBE_PATH", "FFPROBE_BINARY")
    if env:
        return env
    probe = shutil.which("ffprobe")
    if probe:
        return probe
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        name = "ffprobe.exe" if ffmpeg.lower().endswith(".exe") else "ffprobe"
        sibling = _sibling_binary(ffmpeg, name)
        if sibling:
            return sibling
    for folder in _common_ffmpeg_bins():
        for name in ("ffprobe.exe", "ffprobe"):
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)
    return None


def find_ffmpeg() -> str | None:
    env = _env_binary("REPLAY_FFMPEG", "FFMPEG_PATH", "FFMPEG_BINARY")
    if env:
        return env
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    probe = shutil.which("ffprobe")
    if probe:
        name = "ffmpeg.exe" if probe.lower().endswith(".exe") else "ffmpeg"
        sibling = _sibling_binary(probe, name)
        if sibling:
            return sibling
    for folder in _common_ffmpeg_bins():
        for name in ("ffmpeg.exe", "ffmpeg"):
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)
    return None


def _parse_frame_rate(raw: str | None) -> float | None:
    if not raw or raw in {"0/0", "N/A"}:
        return None
    try:
        if "/" in raw:
            num_s, den_s = raw.split("/", 1)
            num, den = float(num_s), float(den_s)
            if den == 0:
                return None
            value = num / den
        else:
            value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value > 240:
        return None
    return round(value, 3)


def parse_ffprobe_payload(payload: dict) -> tuple[float, int, int, float | None]:
    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    duration_raw = fmt.get("duration")
    try:
        duration = float(duration_raw)
    except (TypeError, ValueError):
        duration = 0.0

    width = 0
    height = 0
    fps: float | None = None
    streams = payload.get("streams")
    if isinstance(streams, list):
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if str(stream.get("codec_type") or "") != "video":
                continue
            try:
                width = int(stream.get("width") or 0)
                height = int(stream.get("height") or 0)
            except (TypeError, ValueError):
                width, height = 0, 0
            fps = _parse_frame_rate(str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or ""))
            break

    if duration <= 0 or width <= 0 or height <= 0:
        raise ReplayError(CODE_INVALID_VIDEO)
    if duration > MAX_DURATION_SECONDS:
        raise ReplayError(CODE_TOO_LONG)
    return duration, width, height, fps


def probe_video(path: Path) -> tuple[float, int, int, float | None]:
    binary = find_ffprobe()
    if not binary:
        raise ReplayError(CODE_FFMPEG_UNAVAILABLE)

    cmd = [
        binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReplayError(CODE_INVALID_VIDEO) from exc

    if completed.returncode != 0:
        raise ReplayError(CODE_INVALID_VIDEO)

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ReplayError(CODE_INVALID_VIDEO) from exc
    if not isinstance(payload, dict):
        raise ReplayError(CODE_INVALID_VIDEO)
    return parse_ffprobe_payload(payload)
