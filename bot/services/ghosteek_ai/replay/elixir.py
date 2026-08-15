"""Elixir observations. Never invent numeric elixir without visual/OCR evidence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bot.services.ghosteek_ai.replay.game_state import GS_ELIXIR_HUD_VISIBLE, GameStateObservation
from bot.services.ghosteek_ai.replay.models import SOURCE_HEURISTIC

KIND_OBSERVED = "elixir_observed"
KIND_ESTIMATE = "elixir_estimate"


@dataclass(frozen=True)
class ElixirObservation:
    kind: str
    timestamp: float
    confidence: float
    value: float | None
    source: str = SOURCE_HEURISTIC
    evidence: dict | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "timestamp": round(float(self.timestamp), 3),
            "confidence": round(float(self.confidence), 4),
            "value": None if self.value is None else round(float(self.value), 3),
            "source": self.source,
            "evidence": dict(self.evidence or {}),
        }


class ElixirObserver:
    """
    Without OCR / digit reading, only records that the elixir HUD was visible.

    Never emits numeric elixir_estimate values from heuristics alone.
    """

    def observe(
        self,
        game_states: Sequence[GameStateObservation] = (),
    ) -> list[ElixirObservation]:
        out: list[ElixirObservation] = []
        for gs in game_states:
            if gs.type != GS_ELIXIR_HUD_VISIBLE:
                continue
            if float(gs.confidence) < 0.55:
                continue
            out.append(
                ElixirObservation(
                    kind=KIND_OBSERVED,
                    timestamp=float(gs.timestamp),
                    confidence=float(gs.confidence),
                    value=None,
                    source=SOURCE_HEURISTIC,
                    evidence=dict(gs.evidence),
                )
            )
        return out
