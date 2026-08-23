"""Conservative candidate frame selection for vision analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bot.services.ghosteek_ai.replay.models import (
    OBS_ARENA_VISIBLE,
    OBS_CARD_BAR_VISIBLE,
    OBS_ELIXIR_HUD_VISIBLE,
    FrameSignalSnapshot,
    SIGNAL_TO_OBSERVATION,
    TimelineObservation,
    vision_candidate_min_before_fallback,
    vision_max_frames_per_job,
    vision_min_frame_gap_seconds,
)
from bot.services.ghosteek_ai.replay.sampler import timestamps_for_duration

_SIGNAL_SCORE_MIN = 0.55
_SCORE_DELTA_MIN = 0.12
_SIGNAL_DELTA_MIN = 0.15


@dataclass(frozen=True)
class CandidateFrame:
    frame_index: int
    timestamp_seconds: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "frame_index": int(self.frame_index),
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "reason": self.reason,
        }


class CandidateFrameSelector:
    """Pick a small set of frames worth sending to vision."""

    def __init__(
        self,
        *,
        max_frames: int | None = None,
        min_gap_seconds: float | None = None,
        min_candidates: int | None = None,
    ) -> None:
        self.max_frames = (
            int(max_frames) if max_frames is not None else vision_max_frames_per_job()
        )
        self.min_gap_seconds = (
            float(min_gap_seconds)
            if min_gap_seconds is not None
            else vision_min_frame_gap_seconds()
        )
        self.min_candidates = (
            int(min_candidates)
            if min_candidates is not None
            else vision_candidate_min_before_fallback()
        )

    def select(
        self,
        frames: Sequence[FrameSignalSnapshot],
        *,
        timeline: Sequence[TimelineObservation] | None = None,
        duration_seconds: float | None = None,
    ) -> list[CandidateFrame]:
        if not frames:
            return []

        picked: list[CandidateFrame] = []
        last_ts = -1e9

        def try_add(index: int, ts: float, reason: str) -> bool:
            nonlocal last_ts
            if len(picked) >= self.max_frames:
                return False
            if ts - last_ts < self.min_gap_seconds and picked:
                return False
            if any(p.frame_index == index for p in picked):
                return False
            picked.append(CandidateFrame(frame_index=index, timestamp_seconds=ts, reason=reason))
            last_ts = ts
            return True

        prev_obs: set[str] = set()
        prev_score = float(frames[0].score)
        prev_signals: dict[str, float] = _signal_scores(frames[0])

        for snap in frames:
            cur_obs = _active_observations(snap)
            cur_signals = _signal_scores(snap)
            cur_score = float(snap.score)

            if cur_obs != prev_obs and prev_obs:
                try_add(int(snap.frame_index), float(snap.timestamp), "hud_change")

            if _card_bar_changed(prev_signals, cur_signals):
                try_add(int(snap.frame_index), float(snap.timestamp), "card_bar_change")

            if abs(cur_score - prev_score) >= _SCORE_DELTA_MIN:
                try_add(int(snap.frame_index), float(snap.timestamp), "arena_visual_change")

            if _signal_delta(prev_signals, cur_signals) >= _SIGNAL_DELTA_MIN:
                try_add(int(snap.frame_index), float(snap.timestamp), "signal_delta")

            prev_obs = cur_obs
            prev_score = cur_score
            prev_signals = cur_signals

        if timeline:
            for item in timeline:
                if item.observation_type in {
                    OBS_CARD_BAR_VISIBLE,
                    OBS_ARENA_VISIBLE,
                    OBS_ELIXIR_HUD_VISIBLE,
                }:
                    try_add(
                        int(item.frame_index),
                        float(item.timestamp_seconds),
                        "grounded_observation",
                    )

        if len(picked) < self.min_candidates:
            picked = self._uniform_fallback(
                frames,
                existing=picked,
                duration_seconds=duration_seconds,
            )

        picked.sort(key=lambda c: (c.timestamp_seconds, c.frame_index))
        return picked[: self.max_frames]

    def _uniform_fallback(
        self,
        frames: Sequence[FrameSignalSnapshot],
        *,
        existing: list[CandidateFrame],
        duration_seconds: float | None,
    ) -> list[CandidateFrame]:
        out = list(existing)
        used = {c.frame_index for c in out}
        need = max(0, self.min_candidates - len(out))
        if need <= 0:
            return out

        dur = float(duration_seconds) if duration_seconds is not None else float(frames[-1].timestamp)
        slots = min(self.max_frames - len(out), need)
        if slots <= 0:
            return out

        stamps = timestamps_for_duration(max(dur, 0.05), slots + len(used))
        for ts in stamps:
            if len(out) >= self.max_frames:
                break
            best = min(
                frames,
                key=lambda f: abs(float(f.timestamp) - ts),
            )
            if best.frame_index in used:
                continue
            if out and abs(float(best.timestamp) - out[-1].timestamp_seconds) < self.min_gap_seconds:
                continue
            out.append(
                CandidateFrame(
                    frame_index=int(best.frame_index),
                    timestamp_seconds=float(best.timestamp),
                    reason="uniform_fallback",
                )
            )
            used.add(int(best.frame_index))
        return out


def _signal_scores(snap: FrameSignalSnapshot) -> dict[str, float]:
    out: dict[str, float] = {}
    for sig in snap.signals:
        if sig.score >= _SIGNAL_SCORE_MIN:
            out[sig.signal] = float(sig.score)
    return out


def _active_observations(snap: FrameSignalSnapshot) -> set[str]:
    out: set[str] = set()
    for sig in snap.signals:
        obs = SIGNAL_TO_OBSERVATION.get(sig.signal)
        if obs and sig.score >= _SIGNAL_SCORE_MIN:
            out.add(obs)
    return out


def _card_bar_changed(prev: dict[str, float], cur: dict[str, float]) -> bool:
    key = "card_bar"
    if key not in prev and key not in cur:
        return False
    return abs(cur.get(key, 0.0) - prev.get(key, 0.0)) >= _SIGNAL_DELTA_MIN


def _signal_delta(prev: dict[str, float], cur: dict[str, float]) -> float:
    keys = set(prev) | set(cur)
    if not keys:
        return 0.0
    return max(abs(cur.get(k, 0.0) - prev.get(k, 0.0)) for k in keys)
