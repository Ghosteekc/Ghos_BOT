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
TARGET_SHORT_SIDE = 1080
NEAR_DUP_HAMMING = 6

# Stage 5 vision analyzer
VISION_MAX_FRAMES_DEFAULT = 4
VISION_MAX_FRAMES_MIN = 1
VISION_MAX_FRAMES_MAX = 24
VISION_MIN_GAP_SECONDS_DEFAULT = 1.0
VISION_TIMEOUT_DEFAULT = 90.0
VISION_CONFIDENCE_THRESHOLD_DEFAULT = 0.90
VISION_CANDIDATE_MIN_DEFAULT = 3

# Stage 6 visual evidence
EVIDENCE_ENABLED_DEFAULT = "1"
EVIDENCE_CLIP_ENABLED_DEFAULT = "0"
EVIDENCE_PRE_SECONDS_DEFAULT = 1.5
EVIDENCE_POST_SECONDS_DEFAULT = 1.5
EVIDENCE_MAX_MOMENTS_DEFAULT = 6
EVIDENCE_MAX_MOMENTS_MIN = 1
EVIDENCE_MAX_MOMENTS_MAX = 6
EVIDENCE_WINDOW_SECONDS_MIN = 0.25
EVIDENCE_WINDOW_SECONDS_MAX = 5.0

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


def vision_enabled() -> bool:
    raw = os.environ.get("REPLAY_VISION_ENABLED", "0")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def vision_max_frames_per_job() -> int:
    return _env_int(
        "REPLAY_VISION_MAX_FRAMES_PER_JOB",
        VISION_MAX_FRAMES_DEFAULT,
        VISION_MAX_FRAMES_MIN,
        VISION_MAX_FRAMES_MAX,
    )


def vision_min_frame_gap_seconds() -> float:
    return _env_float(
        "REPLAY_VISION_MIN_FRAME_GAP_SECONDS",
        VISION_MIN_GAP_SECONDS_DEFAULT,
        0.25,
        10.0,
    )


def vision_timeout_seconds() -> float:
    return _env_float(
        "REPLAY_VISION_TIMEOUT_SECONDS",
        VISION_TIMEOUT_DEFAULT,
        10.0,
        300.0,
    )


def vision_frame_delay_seconds() -> float:
    """Pause between Groq vision frame calls to stay under free-tier TPM (~8k/min)."""
    return _env_float(
        "REPLAY_VISION_FRAME_DELAY_SECONDS",
        2.5,
        0.0,
        60.0,
    )


def replay_event_confidence_threshold() -> float:
    return _env_float(
        "REPLAY_EVENT_CONFIDENCE_THRESHOLD",
        VISION_CONFIDENCE_THRESHOLD_DEFAULT,
        0.50,
        0.99,
    )


def vision_candidate_min_before_fallback() -> int:
    return _env_int(
        "REPLAY_VISION_CANDIDATE_MIN",
        VISION_CANDIDATE_MIN_DEFAULT,
        1,
        VISION_MAX_FRAMES_MAX,
    )


def evidence_enabled() -> bool:
    raw = os.environ.get("REPLAY_EVIDENCE_ENABLED", EVIDENCE_ENABLED_DEFAULT)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def evidence_clip_enabled() -> bool:
    raw = os.environ.get("REPLAY_EVIDENCE_CLIP_ENABLED", EVIDENCE_CLIP_ENABLED_DEFAULT)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def evidence_pre_seconds() -> float:
    return _env_float(
        "REPLAY_EVIDENCE_PRE_SECONDS",
        EVIDENCE_PRE_SECONDS_DEFAULT,
        EVIDENCE_WINDOW_SECONDS_MIN,
        EVIDENCE_WINDOW_SECONDS_MAX,
    )


def evidence_post_seconds() -> float:
    return _env_float(
        "REPLAY_EVIDENCE_POST_SECONDS",
        EVIDENCE_POST_SECONDS_DEFAULT,
        EVIDENCE_WINDOW_SECONDS_MIN,
        EVIDENCE_WINDOW_SECONDS_MAX,
    )


def evidence_max_moments() -> int:
    return _env_int(
        "REPLAY_EVIDENCE_MAX_MOMENTS",
        EVIDENCE_MAX_MOMENTS_DEFAULT,
        EVIDENCE_MAX_MOMENTS_MIN,
        EVIDENCE_MAX_MOMENTS_MAX,
    )


# Stage 7: grounded moment explanation (Qwen wording only)
MOMENT_RENDER_ENABLED_DEFAULT = "1"
MOMENT_MAX_DEFAULT = 6
MOMENT_MAX_MIN = 1
MOMENT_MAX_MAX = 6
MOMENT_QWEN_TIMEOUT_DEFAULT = 30.0
MOMENT_QWEN_TIMEOUT_MIN = 5.0
MOMENT_QWEN_TIMEOUT_MAX = 120.0


def moment_render_enabled() -> bool:
    raw = os.environ.get("REPLAY_MOMENT_RENDER_ENABLED", MOMENT_RENDER_ENABLED_DEFAULT)
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def moment_max() -> int:
    return _env_int(
        "REPLAY_MOMENT_MAX",
        MOMENT_MAX_DEFAULT,
        MOMENT_MAX_MIN,
        MOMENT_MAX_MAX,
    )


def moment_qwen_timeout_seconds() -> float:
    return _env_float(
        "REPLAY_MOMENT_QWEN_TIMEOUT_SECONDS",
        MOMENT_QWEN_TIMEOUT_DEFAULT,
        MOMENT_QWEN_TIMEOUT_MIN,
        MOMENT_QWEN_TIMEOUT_MAX,
    )


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

# Vision-only timeline / event observation types (Stage 5)
OBS_CARD_VISIBLE = "card_visible"
OBS_CARD_PLAY_CANDIDATE = "card_play_candidate"
OBS_TROOP_VISIBLE = "troop_visible"
OBS_SPELL_VISIBLE = "spell_visible"
OBS_BUILDING_VISIBLE = "building_visible"
OBS_TOWER_DAMAGE_CANDIDATE = "tower_damage_candidate"
OBS_DEFENSIVE_INTERACTION_CANDIDATE = "defensive_interaction_candidate"
OBS_OFFENSIVE_INTERACTION_CANDIDATE = "offensive_interaction_candidate"

VISION_OBSERVATION_TYPES = frozenset(
    {
        OBS_CARD_VISIBLE,
        OBS_CARD_PLAY_CANDIDATE,
        OBS_TROOP_VISIBLE,
        OBS_SPELL_VISIBLE,
        OBS_BUILDING_VISIBLE,
        OBS_TOWER_DAMAGE_CANDIDATE,
        OBS_DEFENSIVE_INTERACTION_CANDIDATE,
        OBS_OFFENSIVE_INTERACTION_CANDIDATE,
        OBS_UNKNOWN,
    }
)

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
    | VISION_OBSERVATION_TYPES
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
SOURCE_VISION = "vision"
SOURCE_DERIVED = "derived"


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
    vision_observations: tuple = ()


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
    moment_shots: list = field(default_factory=list)
    visual_moments: list = field(default_factory=list)
    grounded_summary: str | None = None
    grounded_limitations: str | None = None
    grounded_summary_source: str | None = None

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
            "moment_shots": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.moment_shots
            ],
            "visual_moments": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.visual_moments
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
            "grounded_summary": self.grounded_summary,
            "grounded_limitations": self.grounded_limitations,
            "grounded_summary_source": self.grounded_summary_source,
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
