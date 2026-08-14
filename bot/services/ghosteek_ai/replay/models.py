"""Stage 3 replay detection models and env clamps.

Does not inspect filenames or invent cards/events.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

STATUS_CR = "cr_replay"
STATUS_NOT_CR = "not_cr_replay"
STATUS_UNCERTAIN = "uncertain"

SAMPLE_FRAMES_DEFAULT = 20
SAMPLE_FRAMES_MIN = 16
SAMPLE_FRAMES_MAX = 24

CR_THRESHOLD_DEFAULT = 0.75
NOT_CR_THRESHOLD_DEFAULT = 0.30

FRAME_TIMEOUT_DEFAULT = 60.0
TARGET_SHORT_SIDE = 720
NEAR_DUP_HAMMING = 6

ALLOWED_STATUS = frozenset({STATUS_CR, STATUS_NOT_CR, STATUS_UNCERTAIN})


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except ValueError:
        return default
    return max(lo, min(hi, value))


def sample_frame_count() -> int:
    return _env_int("REPLAY_SAMPLE_FRAMES", SAMPLE_FRAMES_DEFAULT, SAMPLE_FRAMES_MIN, SAMPLE_FRAMES_MAX)


def frame_timeout_seconds() -> float:
    return _env_float("REPLAY_FRAME_TIMEOUT_SECONDS", FRAME_TIMEOUT_DEFAULT, 20.0, 120.0)


def detection_thresholds() -> tuple[float, float]:
    cr = _env_float("REPLAY_CR_CONFIDENCE_THRESHOLD", CR_THRESHOLD_DEFAULT, 0.60, 0.90)
    not_cr = _env_float("REPLAY_NOT_CR_CONFIDENCE_THRESHOLD", NOT_CR_THRESHOLD_DEFAULT, 0.10, 0.45)
    if not_cr >= cr:
        not_cr = max(0.10, round(cr - 0.25, 2))
    return cr, not_cr


@dataclass(frozen=True)
class HeuristicSignal:
    signal: str
    score: float
    confidence: float
    observation: str


@dataclass(frozen=True)
class FrameScore:
    score: float
    signals: tuple[HeuristicSignal, ...] = ()


@dataclass(frozen=True)
class SampledFrame:
    path: str
    timestamp: float
    width: int
    height: int


@dataclass(frozen=True)
class ReplayDetection:
    status: str
    confidence: float
    frames_analyzed: int
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "confidence": round(self.confidence, 4),
            "frames_analyzed": self.frames_analyzed,
            "observations": list(self.observations),
        }


@dataclass(frozen=True)
class ReplayAnalyzeOutcome:
    filename: str
    mime_type: str
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float | None
    detection: ReplayDetection
