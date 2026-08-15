"""Per-frame game-state observations from HUD signals. Prefer UNKNOWN over guesses."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bot.services.ghosteek_ai.replay.models import (
    SOURCE_HEURISTIC,
    FrameSignalSnapshot,
)

GS_ARENA_VISIBLE = "arena_visible"
GS_PLAYER_HAND_VISIBLE = "player_hand_visible"
GS_OPPONENT_HAND_VISIBLE = "opponent_hand_visible"
GS_ELIXIR_HUD_VISIBLE = "elixir_hud_visible"
GS_BATTLE_TIMER_VISIBLE = "battle_timer_visible"
GS_TOWERS_VISIBLE = "towers_visible"
GS_GAMEPLAY_ACTIVE = "gameplay_active"
GS_RESULT_SCREEN_VISIBLE = "result_screen_visible"

ALLOWED_GAME_STATE_TYPES = frozenset(
    {
        GS_ARENA_VISIBLE,
        GS_PLAYER_HAND_VISIBLE,
        GS_OPPONENT_HAND_VISIBLE,
        GS_ELIXIR_HUD_VISIBLE,
        GS_BATTLE_TIMER_VISIBLE,
        GS_TOWERS_VISIBLE,
        GS_GAMEPLAY_ACTIVE,
        GS_RESULT_SCREEN_VISIBLE,
    }
)

# Signal → game-state mapping (only when confidence is high enough).
_SIGNAL_MAP = {
    "arena_layout": GS_ARENA_VISIBLE,
    "card_bar": GS_PLAYER_HAND_VISIBLE,
    "elixir_hud": GS_ELIXIR_HUD_VISIBLE,
    "gameplay_region": GS_GAMEPLAY_ACTIVE,
    "mobile_aspect": GS_BATTLE_TIMER_VISIBLE,
}


@dataclass(frozen=True)
class GameStateObservation:
    type: str
    timestamp: float
    confidence: float
    source: str
    evidence: dict

    def __post_init__(self) -> None:
        if self.type not in ALLOWED_GAME_STATE_TYPES:
            raise ValueError(f"unknown game state type: {self.type}")

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "timestamp": round(float(self.timestamp), 3),
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "evidence": dict(self.evidence),
        }


class GameStateBuilder:
    """
    Derive structured game-state flags from existing HUD frame signals.

    Does not invent opponent hand / towers / result without a supporting signal.
    """

    def build(self, frames: Sequence[FrameSignalSnapshot]) -> list[GameStateObservation]:
        out: list[GameStateObservation] = []
        for snap in frames:
            by_signal = {s.signal: s for s in snap.signals}
            for signal_name, state_type in _SIGNAL_MAP.items():
                sig = by_signal.get(signal_name)
                if sig is None or float(sig.confidence) < 0.55:
                    continue
                out.append(
                    GameStateObservation(
                        type=state_type,
                        timestamp=float(snap.timestamp),
                        confidence=float(sig.confidence),
                        source=SOURCE_HEURISTIC,
                        evidence={
                            "frame_index": int(snap.frame_index),
                            "signal": signal_name,
                            "score": round(float(sig.score), 4),
                        },
                    )
                )
            # Towers: only when arena + gameplay are both present (layout implies towers UI).
            arena = by_signal.get("arena_layout")
            gameplay = by_signal.get("gameplay_region")
            if (
                arena is not None
                and gameplay is not None
                and float(arena.confidence) >= 0.70
                and float(gameplay.confidence) >= 0.70
            ):
                out.append(
                    GameStateObservation(
                        type=GS_TOWERS_VISIBLE,
                        timestamp=float(snap.timestamp),
                        confidence=min(float(arena.confidence), float(gameplay.confidence), 0.82),
                        source=SOURCE_HEURISTIC,
                        evidence={
                            "frame_index": int(snap.frame_index),
                            "derived_from": ["arena_layout", "gameplay_region"],
                        },
                    )
                )
            # Opponent hand / result screen: no Stage-3 signal → never invent
        return out
