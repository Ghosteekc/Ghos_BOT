"""Vision analyzer contract for replay frame observations. No coaching, no raw MP4 to text LLM."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from bot.services.ghosteek_ai.replay.models import (
    OBS_BUILDING_VISIBLE,
    OBS_CARD_PLAY_CANDIDATE,
    OBS_CARD_VISIBLE,
    OBS_DEFENSIVE_INTERACTION_CANDIDATE,
    OBS_OFFENSIVE_INTERACTION_CANDIDATE,
    OBS_SPELL_VISIBLE,
    OBS_TOWER_DAMAGE_CANDIDATE,
    OBS_TROOP_VISIBLE,
    OBS_UNKNOWN,
    SOURCE_VISION,
    VISION_OBSERVATION_TYPES,
)

VISION_EVENT_TYPES = frozenset(VISION_OBSERVATION_TYPES)

SIDE_PLAYER = "player"
SIDE_OPPONENT = "opponent"
SIDE_UNKNOWN = "unknown"
ALLOWED_SIDES = frozenset({SIDE_PLAYER, SIDE_OPPONENT, SIDE_UNKNOWN})

LANE_LEFT = "left"
LANE_RIGHT = "right"
LANE_CENTER = "center"
LANE_UNKNOWN = "unknown"
ALLOWED_LANES = frozenset({LANE_LEFT, LANE_RIGHT, LANE_CENTER, LANE_UNKNOWN})

_EVENT_ALIASES = {
    "card_identity_visible": OBS_CARD_VISIBLE,
    "card_play": OBS_CARD_PLAY_CANDIDATE,
    "troop": OBS_TROOP_VISIBLE,
    "spell": OBS_SPELL_VISIBLE,
    "building": OBS_BUILDING_VISIBLE,
}


@dataclass(frozen=True)
class VisionObservation:
    """Structured vision output — observation only, never coaching."""

    timestamp_seconds: float
    frame_index: int
    event_type: str
    confidence: float
    source: str = SOURCE_VISION
    card_name: str | None = None
    card_id: str | None = None
    side: str = SIDE_UNKNOWN
    lane: str = LANE_UNKNOWN
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = _EVENT_ALIASES.get(self.event_type, self.event_type)
        if normalized not in VISION_EVENT_TYPES:
            raise ValueError(f"unknown vision event_type: {self.event_type}")
        if normalized != self.event_type:
            object.__setattr__(self, "event_type", normalized)
        if self.side not in ALLOWED_SIDES:
            object.__setattr__(self, "side", SIDE_UNKNOWN)
        if self.lane not in ALLOWED_LANES:
            object.__setattr__(self, "lane", LANE_UNKNOWN)
        conf = float(self.confidence)
        if conf < 0:
            conf = 0.0
        elif conf > 1:
            conf = 1.0
        object.__setattr__(self, "confidence", conf)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "frame_index": int(self.frame_index),
            "event_type": self.event_type,
            "card_name": self.card_name,
            "card_id": self.card_id,
            "side": self.side,
            "lane": self.lane,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "details": dict(self.details),
        }


class VisionAnalyzer(ABC):
    """Adapter boundary — swap Ollama / other vision backends without touching replay pipeline."""

    @abstractmethod
    async def analyze_frame(
        self,
        frame_path: str,
        *,
        frame_index: int,
        timestamp_seconds: float,
    ) -> list[VisionObservation]:
        """Analyze one candidate frame and return structured observations."""

    async def analyze_frame_sequence(
        self,
        frames: Sequence[tuple[str, int, float]],
    ) -> list[VisionObservation]:
        """Analyze multiple (path, frame_index, timestamp) tuples in order."""
        out: list[VisionObservation] = []
        for path, index, ts in frames:
            out.extend(
                await self.analyze_frame(
                    path,
                    frame_index=int(index),
                    timestamp_seconds=float(ts),
                )
            )
        return out


class NullVisionAnalyzer(VisionAnalyzer):
    """No-op analyzer when vision is disabled or unavailable."""

    async def analyze_frame(
        self,
        frame_path: str,
        *,
        frame_index: int,
        timestamp_seconds: float,
    ) -> list[VisionObservation]:
        del frame_path, frame_index, timestamp_seconds
        return []


def normalize_event_type(raw: str | None) -> str | None:
    if not raw:
        return None
    key = str(raw).strip().lower()
    if not key:
        return None
    mapped = _EVENT_ALIASES.get(key, key)
    if mapped not in VISION_EVENT_TYPES:
        return None
    return mapped


def normalize_side(raw: str | None) -> str:
    if not raw:
        return SIDE_UNKNOWN
    key = str(raw).strip().lower()
    if key in {"self", "ally", "friendly"}:
        return SIDE_PLAYER
    if key in {"enemy", "opp"}:
        return SIDE_OPPONENT
    if key in ALLOWED_SIDES:
        return key
    return SIDE_UNKNOWN


def normalize_lane(raw: str | None) -> str:
    if not raw:
        return LANE_UNKNOWN
    key = str(raw).strip().lower()
    if key in ALLOWED_LANES:
        return key
    return LANE_UNKNOWN
