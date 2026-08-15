"""Chronological battle timeline from ReplayEvents. No coaching, no invented events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact
from bot.services.ghosteek_ai.replay.events import (
    CONF_CONFIRMED,
    EVENT_BATTLE_ENDED,
    EVENT_BATTLE_STARTED,
    EVENT_CARD_PLAY,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_VISIBLE,
    EVENT_OVERTIME_STARTED,
    EVENT_RESULT_VISIBLE,
    ReplayEvent,
)

PHASE_OPENING = "opening"
PHASE_MID_GAME = "mid_game"
PHASE_OVERTIME = "overtime"
PHASE_ENDING = "ending"

ALLOWED_PHASES = frozenset(
    {PHASE_OPENING, PHASE_MID_GAME, PHASE_OVERTIME, PHASE_ENDING}
)

# Same-timestamp tie-break (lower = earlier). Sort only — never invent events.
_EVENT_SORT_RANK = {
    EVENT_BATTLE_STARTED: 0,
    EVENT_CARD_PLAY: 1,
    EVENT_CARD_PLAY_CANDIDATE: 2,
    EVENT_CARD_VISIBLE: 3,
    EVENT_OVERTIME_STARTED: 4,
    EVENT_RESULT_VISIBLE: 5,
    EVENT_BATTLE_ENDED: 6,
}

_UNKNOWN_GAP_SECONDS = 2.0


@dataclass(frozen=True)
class UnknownInterval:
    start: float
    end: float
    status: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "from": round(float(self.start), 3),
            "to": round(float(self.end), 3),
            "status": self.status,
        }


@dataclass(frozen=True)
class BattlePhaseMark:
    """Phase asserted only when backed by confirmed evidence."""

    phase: str
    timestamp_seconds: float
    confidence: float

    def __post_init__(self) -> None:
        if self.phase not in ALLOWED_PHASES:
            raise ValueError(f"unknown phase: {self.phase}")

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "confidence": round(float(self.confidence), 4),
        }


@dataclass(frozen=True)
class BattleTimelineSummary:
    confirmed_event_count: int
    confirmed_card_count: int
    first_event: float | None
    last_event: float | None
    known_duration: float
    unknown_intervals_count: int

    def to_dict(self) -> dict:
        return {
            "confirmed_event_count": int(self.confirmed_event_count),
            "confirmed_card_count": int(self.confirmed_card_count),
            "first_event": (
                None if self.first_event is None else round(float(self.first_event), 3)
            ),
            "last_event": (
                None if self.last_event is None else round(float(self.last_event), 3)
            ),
            "known_duration": round(float(self.known_duration), 3),
            "unknown_intervals_count": int(self.unknown_intervals_count),
        }


@dataclass(frozen=True)
class ReplayBattleTimeline:
    duration_seconds: float
    events: list[ReplayEvent] = field(default_factory=list)
    confirmed_events: list[ReplayEvent] = field(default_factory=list)
    unknown_intervals: list[UnknownInterval] = field(default_factory=list)
    confidence: float = 0.0
    phases: list[BattlePhaseMark] = field(default_factory=list)
    summary: BattleTimelineSummary | None = None

    def to_dict(self) -> dict:
        summary = (
            self.summary.to_dict()
            if self.summary is not None
            else _empty_summary().to_dict()
        )
        return {
            "duration_seconds": round(float(self.duration_seconds), 3),
            "events": [e.to_dict() for e in self.events],
            "confirmed_events": [e.to_dict() for e in self.confirmed_events],
            "unknown_intervals": [u.to_dict() for u in self.unknown_intervals],
            "confidence": round(float(self.confidence), 4),
            "phases": [p.to_dict() for p in self.phases],
            "summary": summary,
        }


class ReplayBattleTimelineBuilder:
    """Assemble chronological battle timeline from Stage 5B events."""

    def build(
        self,
        *,
        duration_seconds: float,
        events: Sequence[ReplayEvent] = (),
        confirmed_events: Sequence[ReplayEvent] | None = None,
        confirmed_cards: Sequence[ConfirmedCardFact] = (),
        confidence: float | None = None,
    ) -> ReplayBattleTimeline:
        sorted_events = sort_events(events)
        if confirmed_events is None:
            confirmed = [
                e
                for e in sorted_events
                if float(e.confidence) >= CONF_CONFIRMED
                and e.event_type != EVENT_CARD_PLAY_CANDIDATE
            ]
        else:
            confirmed = sort_events(confirmed_events)

        unknowns = build_unknown_intervals(confirmed)
        phases = build_confirmed_phases(confirmed)
        card_ids = {c.card_id for c in confirmed_cards}
        for ev in confirmed:
            if ev.card_id:
                card_ids.add(ev.card_id)

        first = confirmed[0].timestamp_seconds if confirmed else None
        last = confirmed[-1].timestamp_seconds if confirmed else None
        known = 0.0 if first is None or last is None else max(0.0, float(last) - float(first))

        summary = BattleTimelineSummary(
            confirmed_event_count=len(confirmed),
            confirmed_card_count=len(card_ids),
            first_event=first,
            last_event=last,
            known_duration=known,
            unknown_intervals_count=len(unknowns),
        )

        if confidence is None:
            if confirmed:
                conf = min(float(e.confidence) for e in confirmed)
            elif sorted_events:
                conf = min(float(e.confidence) for e in sorted_events)
            else:
                conf = 0.0
        else:
            conf = float(confidence)

        return ReplayBattleTimeline(
            duration_seconds=float(duration_seconds),
            events=list(sorted_events),
            confirmed_events=list(confirmed),
            unknown_intervals=unknowns,
            confidence=conf,
            phases=phases,
            summary=summary,
        )


def sort_events(events: Sequence[ReplayEvent]) -> list[ReplayEvent]:
    return sorted(
        events,
        key=lambda e: (
            float(e.timestamp_seconds),
            _EVENT_SORT_RANK.get(e.event_type, 99),
            e.card_id or "",
            e.player,
        ),
    )


def build_unknown_intervals(
    confirmed_events: Sequence[ReplayEvent],
    *,
    min_gap_seconds: float = _UNKNOWN_GAP_SECONDS,
) -> list[UnknownInterval]:
    """Gaps between consecutive confirmed events — never filled with guesses."""
    if len(confirmed_events) < 2:
        return []
    ordered = sort_events(confirmed_events)
    out: list[UnknownInterval] = []
    for prev, nxt in zip(ordered, ordered[1:]):
        gap = float(nxt.timestamp_seconds) - float(prev.timestamp_seconds)
        if gap > min_gap_seconds:
            out.append(
                UnknownInterval(
                    start=float(prev.timestamp_seconds),
                    end=float(nxt.timestamp_seconds),
                    status="unknown",
                )
            )
    return out


def build_confirmed_phases(confirmed_events: Sequence[ReplayEvent]) -> list[BattlePhaseMark]:
    """Emit phases only when backed by confirmed events. No negative overtime claim."""
    if not confirmed_events:
        return []
    ordered = sort_events(confirmed_events)
    phases: list[BattlePhaseMark] = []

    started = next((e for e in ordered if e.event_type == EVENT_BATTLE_STARTED), None)
    if started is not None:
        phases.append(
            BattlePhaseMark(
                phase=PHASE_OPENING,
                timestamp_seconds=float(started.timestamp_seconds),
                confidence=float(started.confidence),
            )
        )

    overtime = next((e for e in ordered if e.event_type == EVENT_OVERTIME_STARTED), None)
    if overtime is not None:
        phases.append(
            BattlePhaseMark(
                phase=PHASE_OVERTIME,
                timestamp_seconds=float(overtime.timestamp_seconds),
                confidence=float(overtime.confidence),
            )
        )

    ending = next(
        (e for e in ordered if e.event_type in {EVENT_RESULT_VISIBLE, EVENT_BATTLE_ENDED}),
        None,
    )
    if ending is not None:
        phases.append(
            BattlePhaseMark(
                phase=PHASE_ENDING,
                timestamp_seconds=float(ending.timestamp_seconds),
                confidence=float(ending.confidence),
            )
        )

    open_ts = float(started.timestamp_seconds) if started else None
    end_ts = float(ending.timestamp_seconds) if ending else None
    if open_ts is not None and end_ts is not None and end_ts > open_ts:
        mid_ev = next(
            (
                e
                for e in ordered
                if open_ts < float(e.timestamp_seconds) < end_ts
                and e.event_type
                not in {
                    EVENT_BATTLE_STARTED,
                    EVENT_RESULT_VISIBLE,
                    EVENT_BATTLE_ENDED,
                    EVENT_OVERTIME_STARTED,
                }
            ),
            None,
        )
        if mid_ev is not None:
            phases.append(
                BattlePhaseMark(
                    phase=PHASE_MID_GAME,
                    timestamp_seconds=float(mid_ev.timestamp_seconds),
                    confidence=float(mid_ev.confidence),
                )
            )

    phases.sort(key=lambda p: (p.timestamp_seconds, p.phase))
    return phases


def _empty_summary() -> BattleTimelineSummary:
    return BattleTimelineSummary(
        confirmed_event_count=0,
        confirmed_card_count=0,
        first_event=None,
        last_event=None,
        known_duration=0.0,
        unknown_intervals_count=0,
    )
