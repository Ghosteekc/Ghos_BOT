"""Stage 6: grounded visual evidence for confirmed vision observations.

VisionObservation → nearest real sampled timestamp → JPEG (+ optional short clip).
No coaching, no invented events, no absolute filesystem paths in API payloads.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# re-export used helpers for tests
__all__ = [
    "EvidenceBuilder",
    "EvidenceFrame",
    "EvidenceStore",
    "ReplayVisualMoment",
    "get_evidence_store",
]

from bot.services.ghosteek_ai.replay.models import (
    OBS_CARD_PLAY_CANDIDATE,
    OBS_UNKNOWN,
    SOURCE_VISION,
    FrameSignalSnapshot,
    evidence_clip_enabled,
    evidence_enabled,
    evidence_max_moments,
    evidence_post_seconds,
    evidence_pre_seconds,
    replay_event_confidence_threshold,
)
from bot.services.ghosteek_ai.replay.sampler import scaled_dimensions
from bot.services.ghosteek_ai.replay.validator import find_ffmpeg
from bot.services.ghosteek_ai.replay.vision_analyzer import VisionObservation

logger = logging.getLogger(__name__)

EVIDENCE_DISPLAY_SHORT_SIDE = 720
EVIDENCE_JPEG_Q = 5  # ffmpeg -q:v (lower = better); 5 ≈ moderate
EVIDENCE_DEDUPE_WINDOW_SECONDS = 1.5
EVIDENCE_MAX_FILE_BYTES = 2 * 1024 * 1024
EVIDENCE_CLIP_MAX_FILE_BYTES = 4 * 1024 * 1024
_EXTRACT_TIMEOUT = 8.0
_CLIP_TIMEOUT = 20.0
_STORE_TTL_SECONDS = 900.0
_STORE_MAX_ITEMS = 64

_SKIP_EVENT_TYPES = frozenset({OBS_UNKNOWN, OBS_CARD_PLAY_CANDIDATE, "unknown"})


@dataclass(frozen=True)
class EvidenceFrame:
    frame_index: int
    timestamp_seconds: float
    path: str | None = None
    width: int = 0
    height: int = 0

    def to_public_dict(self) -> dict:
        """API-safe metadata — never includes filesystem paths."""
        out: dict = {
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "frame_index": int(self.frame_index),
        }
        if self.width:
            out["width"] = int(self.width)
        if self.height:
            out["height"] = int(self.height)
        return out


@dataclass(frozen=True)
class ReplayVisualMoment:
    event_type: str
    timestamp_seconds: float
    confidence: float
    evidence_frame: EvidenceFrame
    card_name: str | None = None
    clip_path: str | None = None
    evidence_id: str | None = None
    clip_id: str | None = None
    preview_base64: str | None = None
    clip_available: bool = False
    source: str = SOURCE_VISION
    title: str | None = None
    short_description: str | None = None
    explanation_kind: str | None = None
    explanation_source: str | None = None

    def to_dict(self) -> dict:
        out: dict = {
            "event_type": self.event_type,
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "card_name": self.card_name,
            "confidence": round(float(self.confidence), 4),
            "evidence_frame": self.evidence_frame.to_public_dict(),
            "evidence_id": self.evidence_id,
            "clip_id": self.clip_id if self.clip_available else None,
            "clip_available": bool(self.clip_available),
            "preview_base64": self.preview_base64,
            "source": self.source,
        }
        if self.title is not None:
            out["title"] = self.title
        if self.short_description is not None:
            out["short_description"] = self.short_description
        if self.explanation_kind is not None:
            out["explanation_kind"] = self.explanation_kind
        if self.explanation_source is not None:
            out["explanation_source"] = self.explanation_source
        return out


@dataclass
class _StoreEntry:
    data: bytes
    content_type: str
    created_at: float


class EvidenceStore:
    """Process-local TTL store. Opaque IDs only — never user filenames."""

    def __init__(
        self,
        *,
        ttl_seconds: float = _STORE_TTL_SECONDS,
        max_items: int = _STORE_MAX_ITEMS,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._max = int(max_items)
        self._lock = threading.Lock()
        self._items: dict[str, _StoreEntry] = {}

    def put(self, data: bytes, *, content_type: str) -> str:
        if not data:
            raise ValueError("empty evidence payload")
        token = secrets.token_urlsafe(16)
        now = time.monotonic()
        with self._lock:
            self._purge_locked(now)
            while len(self._items) >= self._max:
                oldest = min(self._items, key=lambda k: self._items[k].created_at)
                del self._items[oldest]
            self._items[token] = _StoreEntry(
                data=data,
                content_type=content_type,
                created_at=now,
            )
        return token

    def get(self, evidence_id: str) -> tuple[bytes, str] | None:
        if not evidence_id or not isinstance(evidence_id, str):
            return None
        if "/" in evidence_id or "\\" in evidence_id or ".." in evidence_id:
            return None
        if len(evidence_id) > 64:
            return None
        now = time.monotonic()
        with self._lock:
            self._purge_locked(now)
            entry = self._items.get(evidence_id)
            if entry is None:
                return None
            return entry.data, entry.content_type

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def _purge_locked(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._items.items()
            if (now - entry.created_at) > self._ttl
        ]
        for key in expired:
            del self._items[key]


_EVIDENCE_STORE = EvidenceStore()


def get_evidence_store() -> EvidenceStore:
    return _EVIDENCE_STORE


class EvidenceBuilder:
    """Build grounded visual moments from confirmed vision observations only."""

    def __init__(
        self,
        *,
        store: EvidenceStore | None = None,
        confidence_threshold: float | None = None,
        max_moments: int | None = None,
        pre_seconds: float | None = None,
        post_seconds: float | None = None,
        clip_enabled: bool | None = None,
        dedupe_window_seconds: float = EVIDENCE_DEDUPE_WINDOW_SECONDS,
    ) -> None:
        self._store = store if store is not None else get_evidence_store()
        self._threshold = (
            float(confidence_threshold)
            if confidence_threshold is not None
            else replay_event_confidence_threshold()
        )
        self._max = int(max_moments) if max_moments is not None else evidence_max_moments()
        self._pre = float(pre_seconds) if pre_seconds is not None else evidence_pre_seconds()
        self._post = float(post_seconds) if post_seconds is not None else evidence_post_seconds()
        self._clips = (
            bool(clip_enabled) if clip_enabled is not None else evidence_clip_enabled()
        )
        self._dedupe = float(dedupe_window_seconds)

    def build(
        self,
        *,
        video_path: Path,
        duration_seconds: float,
        src_width: int,
        src_height: int,
        vision_observations: Sequence[VisionObservation],
        sampled_frames: Sequence[FrameSignalSnapshot] = (),
    ) -> list[ReplayVisualMoment]:
        if not evidence_enabled():
            return []
        if not vision_observations:
            return []

        binary = find_ffmpeg()
        if not binary:
            logger.warning("evidence skipped: ffmpeg unavailable")
            return []

        selected = self._select_observations(vision_observations)
        if not selected:
            return []

        out_w, out_h = scaled_dimensions(
            src_width, src_height, short_side=EVIDENCE_DISPLAY_SHORT_SIDE
        )
        moments: list[ReplayVisualMoment] = []
        job_tmpdir = Path(tempfile.mkdtemp(prefix="ghosteek-replay-evidence-"))
        try:
            for obs in selected:
                nearest = _nearest_sampled_frame(obs, sampled_frames)
                frame_index = int(nearest.frame_index) if nearest else int(obs.frame_index)
                frame_ts = (
                    float(nearest.timestamp) if nearest else float(obs.timestamp_seconds)
                )
                frame_ts = _clamp(frame_ts, 0.0, max(0.0, float(duration_seconds)))

                jpeg_path = job_tmpdir / f"frame_{frame_index}_{secrets.token_hex(4)}.jpg"
                if not _extract_jpeg(
                    binary=binary,
                    video_path=video_path,
                    timestamp=frame_ts,
                    dest=jpeg_path,
                    width=out_w,
                    height=out_h,
                ):
                    continue

                try:
                    jpeg_bytes = jpeg_path.read_bytes()
                except OSError:
                    continue
                if not jpeg_bytes or len(jpeg_bytes) > EVIDENCE_MAX_FILE_BYTES:
                    continue

                evidence_id = self._store.put(jpeg_bytes, content_type="image/jpeg")
                preview_b64 = base64.b64encode(jpeg_bytes).decode("ascii")

                clip_id: str | None = None
                clip_available = False
                if self._clips:
                    clip_path = job_tmpdir / f"clip_{frame_index}_{secrets.token_hex(4)}.webp"
                    if _extract_clip(
                        binary=binary,
                        video_path=video_path,
                        center_ts=float(obs.timestamp_seconds),
                        duration_seconds=float(duration_seconds),
                        pre_seconds=self._pre,
                        post_seconds=self._post,
                        dest=clip_path,
                        width=out_w,
                        height=out_h,
                    ):
                        try:
                            clip_bytes = clip_path.read_bytes()
                        except OSError:
                            clip_bytes = b""
                        if clip_bytes and len(clip_bytes) <= EVIDENCE_CLIP_MAX_FILE_BYTES:
                            clip_id = self._store.put(
                                clip_bytes, content_type="image/webp"
                            )
                            clip_available = True

                moments.append(
                    ReplayVisualMoment(
                        event_type=obs.event_type,
                        timestamp_seconds=float(obs.timestamp_seconds),
                        confidence=float(obs.confidence),
                        card_name=obs.card_name,
                        evidence_frame=EvidenceFrame(
                            frame_index=frame_index,
                            timestamp_seconds=frame_ts,
                            path=None,
                            width=out_w,
                            height=out_h,
                        ),
                        evidence_id=evidence_id,
                        clip_id=clip_id,
                        preview_base64=preview_b64,
                        clip_available=clip_available,
                        source=SOURCE_VISION,
                    )
                )
                if len(moments) >= self._max:
                    break
        finally:
            shutil.rmtree(job_tmpdir, ignore_errors=True)

        return moments

    def _select_observations(
        self, observations: Sequence[VisionObservation]
    ) -> list[VisionObservation]:
        ranked = sorted(
            observations,
            key=lambda o: (
                -float(o.confidence),
                float(o.timestamp_seconds),
                int(o.frame_index),
            ),
        )
        picked: list[VisionObservation] = []
        for obs in ranked:
            if float(obs.confidence) < self._threshold:
                continue
            if obs.event_type in _SKIP_EVENT_TYPES:
                continue
            if _is_duplicate(obs, picked, window=self._dedupe):
                continue
            picked.append(obs)
            if len(picked) >= self._max:
                break
        picked.sort(key=lambda o: (float(o.timestamp_seconds), int(o.frame_index)))
        return picked


def _nearest_sampled_frame(
    obs: VisionObservation,
    sampled: Sequence[FrameSignalSnapshot],
) -> FrameSignalSnapshot | None:
    if not sampled:
        return None
    for snap in sampled:
        if int(snap.frame_index) == int(obs.frame_index):
            return snap
    return min(
        sampled,
        key=lambda s: abs(float(s.timestamp) - float(obs.timestamp_seconds)),
    )


def _is_duplicate(
    obs: VisionObservation,
    picked: Sequence[VisionObservation],
    *,
    window: float,
) -> bool:
    for prev in picked:
        if prev.event_type != obs.event_type:
            continue
        if abs(float(prev.timestamp_seconds) - float(obs.timestamp_seconds)) <= window:
            if (prev.card_name or "") == (obs.card_name or ""):
                return True
    return False


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _extract_jpeg(
    *,
    binary: str,
    video_path: Path,
    timestamp: float,
    dest: Path,
    width: int,
    height: int,
) -> bool:
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
        str(EVIDENCE_JPEG_Q),
        "-y",
        str(dest),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            timeout=_EXTRACT_TIMEOUT,
            check=False,
            **_subprocess_kwargs(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return completed.returncode == 0 and dest.is_file() and dest.stat().st_size > 0


def _extract_clip(
    *,
    binary: str,
    video_path: Path,
    center_ts: float,
    duration_seconds: float,
    pre_seconds: float,
    post_seconds: float,
    dest: Path,
    width: int,
    height: int,
) -> bool:
    start = _clamp(center_ts - pre_seconds, 0.0, max(0.0, duration_seconds))
    end = _clamp(center_ts + post_seconds, 0.0, max(0.0, duration_seconds))
    if end <= start + 0.05:
        end = _clamp(start + 0.5, 0.0, max(0.0, duration_seconds))
    clip_dur = max(0.1, end - start)
    vf = f"scale={width}:{height}:flags=lanczos,fps=8"
    cmd = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{clip_dur:.3f}",
        "-vf",
        vf,
        "-an",
        "-loop",
        "0",
        "-y",
        str(dest),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            timeout=_CLIP_TIMEOUT,
            check=False,
            **_subprocess_kwargs(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return completed.returncode == 0 and dest.is_file() and dest.stat().st_size > 0


def _subprocess_kwargs() -> dict:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
