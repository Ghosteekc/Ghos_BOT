"""Build a conservative HUD timeline from Stage 3 frame signals. No LLM, no card events."""

from __future__ import annotations

from bot.services.ghosteek_ai.replay.models import (
    OBS_UNKNOWN,
    SIGNAL_TO_OBSERVATION,
    SOURCE_HEURISTIC,
    DetectionBundle,
    FrameSignalSnapshot,
    TimelineObservation,
)

_SIGNAL_SCORE_MIN = 0.55


class ReplayTimelineBuilder:
    """Map per-frame heuristic signals → typed timeline observations."""

    def build(self, frames: list[FrameSignalSnapshot] | tuple[FrameSignalSnapshot, ...]) -> list[TimelineObservation]:
        out: list[TimelineObservation] = []
        for snap in frames:
            emitted = 0
            for sig in snap.signals:
                obs_type = SIGNAL_TO_OBSERVATION.get(sig.signal)
                if not obs_type:
                    continue
                if sig.score < _SIGNAL_SCORE_MIN:
                    continue
                confidence = max(0.0, min(1.0, float(sig.score) * float(sig.confidence)))
                if confidence < 0.30:
                    continue
                out.append(
                    TimelineObservation(
                        timestamp_seconds=float(snap.timestamp),
                        frame_index=int(snap.frame_index),
                        observation_type=obs_type,
                        confidence=round(confidence, 4),
                        source=SOURCE_HEURISTIC,
                    )
                )
                emitted += 1
            if emitted == 0:
                out.append(
                    TimelineObservation(
                        timestamp_seconds=float(snap.timestamp),
                        frame_index=int(snap.frame_index),
                        observation_type=OBS_UNKNOWN,
                        confidence=round(max(0.0, min(1.0, float(snap.score))), 4),
                        source=SOURCE_HEURISTIC,
                    )
                )
        out.sort(key=lambda item: (item.timestamp_seconds, item.frame_index, item.observation_type))
        return out

    def build_from_bundle(self, bundle: DetectionBundle) -> list[TimelineObservation]:
        return self.build(bundle.frames)
