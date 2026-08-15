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

# Adaptive event sampling (Stage 5 full recognition)
ANALYSIS_FPS_DEFAULT = 3.0
ANALYSIS_FPS_MIN = 2.0
ANALYSIS_FPS_MAX = 4.0
EVENT_FPS_DEFAULT = 8.0
EVENT_FPS_MIN = 6.0
EVENT_FPS_MAX = 10.0
MAX_FRAMES_DEFAULT = 96
MAX_FRAMES_MIN = 24
MAX_FRAMES_MAX = 180
MAX_CONCURRENT_JOBS_DEFAULT = 1
CHANGE_HASH_HAMMING = 10

CR_THRESHOLD_DEFAULT = 0.75
NOT_CR_THRESHOLD_DEFAULT = 0.30

FRAME_TIMEOUT_DEFAULT = 120.0
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
    return _env_float("REPLAY_FRAME_TIMEOUT_SECONDS", FRAME_TIMEOUT_DEFAULT, 20.0, 300.0)


def analysis_fps() -> float:
    return _env_float("REPLAY_ANALYSIS_FPS", ANALYSIS_FPS_DEFAULT, ANALYSIS_FPS_MIN, ANALYSIS_FPS_MAX)


def event_fps() -> float:
    return _env_float("REPLAY_EVENT_FPS", EVENT_FPS_DEFAULT, EVENT_FPS_MIN, EVENT_FPS_MAX)


def max_analysis_frames() -> int:
    return _env_int("REPLAY_MAX_FRAMES", MAX_FRAMES_DEFAULT, MAX_FRAMES_MIN, MAX_FRAMES_MAX)


def max_concurrent_jobs() -> int:
    return _env_int("REPLAY_MAX_CONCURRENT_JOBS", MAX_CONCURRENT_JOBS_DEFAULT, 1, 1)


def adaptive_sampling_enabled() -> bool:
    raw = os.environ.get("REPLAY_ADAPTIVE_SAMPLING", "1")
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


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


# --- Stage 4: timeline + facts (no LLM, no card/event invention) ---

OBS_GAMEPLAY_SCREEN = "gameplay_screen"
OBS_ARENA_VISIBLE = "arena_visible"
OBS_CARD_BAR_VISIBLE = "card_bar_visible"
OBS_ELIXIR_HUD_VISIBLE = "elixir_hud_visible"
OBS_BATTLE_UI_VISIBLE = "battle_ui_visible"
OBS_RESULT_SCREEN = "result_screen"
OBS_UNKNOWN = "unknown"

OBSERVATION_TYPES = frozenset(
    {
        OBS_GAMEPLAY_SCREEN,
        OBS_ARENA_VISIBLE,
        OBS_CARD_BAR_VISIBLE,
        OBS_ELIXIR_HUD_VISIBLE,
        OBS_BATTLE_UI_VISIBLE,
        OBS_RESULT_SCREEN,
        OBS_UNKNOWN,
    }
)

SIGNAL_TO_OBSERVATION = {
    "gameplay_region": OBS_GAMEPLAY_SCREEN,
    "arena_layout": OBS_ARENA_VISIBLE,
    "card_bar": OBS_CARD_BAR_VISIBLE,
    "elixir_hud": OBS_ELIXIR_HUD_VISIBLE,
    "mobile_aspect": OBS_BATTLE_UI_VISIBLE,
}

DEFAULT_LIMITATIONS = (
    "card_play_events_not_detected",
    "card_play_events_not_confirmed",
    "exact_card_timing_unavailable",
    "elixir_values_not_extracted",
    "damage_events_not_detected",
    "deck_identity_not_confirmed",
)

DEFAULT_UNAVAILABLE = (
    "exact elixir",
    "tower HP",
    "damage events",
    "winner from video alone",
)

SOURCE_HEURISTIC = "heuristic"


@dataclass(frozen=True)
class FrameSignalSnapshot:
    frame_index: int
    timestamp: float
    score: float
    signals: tuple[HeuristicSignal, ...] = ()


@dataclass(frozen=True)
class DetectionBundle:
    detection: ReplayDetection
    frames: tuple[FrameSignalSnapshot, ...] = ()
    confirmed_card_observations: tuple = ()
    ambiguous_card_observations: tuple = ()
    game_state_observations: tuple = ()


@dataclass(frozen=True)
class TimelineObservation:
    timestamp_seconds: float
    frame_index: int
    observation_type: str
    confidence: float
    source: str = SOURCE_HEURISTIC

    def __post_init__(self) -> None:
        if self.observation_type not in OBSERVATION_TYPES:
            raise ValueError(f"unknown observation_type: {self.observation_type}")

    def to_dict(self) -> dict:
        return {
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "frame_index": int(self.frame_index),
            "observation_type": self.observation_type,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
        }


@dataclass(frozen=True)
class ReplayAnalysisResult:
    status: str
    confidence: float
    duration_seconds: float
    frames_analyzed: int
    timeline: list[TimelineObservation] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    confirmed_cards: list = field(default_factory=list)
    ambiguous_cards: list = field(default_factory=list)
    events: list = field(default_factory=list)
    confirmed_events: list = field(default_factory=list)
    candidate_events: list = field(default_factory=list)
    battle_timeline: object | None = None
    tactical_analysis: object | None = None
    coach_reply: str | None = None
    coach_source: str | None = None
    game_state_observations: list = field(default_factory=list)
    elixir_observations: list = field(default_factory=list)
    cycle: object | None = None
    what_is_confirmed: list[str] = field(default_factory=list)
    what_is_uncertain: list[str] = field(default_factory=list)
    what_is_unavailable: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": "replay_analysis",
            "replay_status": self.status,
            "confidence": round(float(self.confidence), 4),
            "duration_seconds": round(float(self.duration_seconds), 3),
            "frames_analyzed": int(self.frames_analyzed),
            "timeline": [item.to_dict() for item in self.timeline],
            "facts": list(self.facts),
            "limitations": list(self.limitations),
            "confirmed_cards": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.confirmed_cards
            ],
            "ambiguous_cards": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.ambiguous_cards
            ],
            "events": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.events
            ],
            "confirmed_events": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.confirmed_events
            ],
            "candidate_events": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.candidate_events
            ],
            "battle_timeline": (
                self.battle_timeline.to_dict()
                if self.battle_timeline is not None and hasattr(self.battle_timeline, "to_dict")
                else None
            ),
            "tactical_analysis": (
                self.tactical_analysis.to_dict()
                if self.tactical_analysis is not None and hasattr(self.tactical_analysis, "to_dict")
                else None
            ),
            "coach_reply": self.coach_reply,
            "coach_source": self.coach_source,
            "game_state_observations": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.game_state_observations
            ],
            "elixir_observations": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.elixir_observations
            ],
            "cycle": (
                self.cycle.to_dict()
                if self.cycle is not None and hasattr(self.cycle, "to_dict")
                else self.cycle
            ),
            "what_is_confirmed": list(self.what_is_confirmed),
            "what_is_uncertain": list(self.what_is_uncertain),
            "what_is_unavailable": list(self.what_is_unavailable),
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
    analysis: ReplayAnalysisResult | None = None
