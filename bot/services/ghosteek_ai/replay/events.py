"""Conservative replay gameplay events from confirmed observations. No LLM."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bot.services.ghosteek_ai.replay.card_recognizer import (
    LOC_OPPONENT_HAND,
    LOC_PLAYED_AREA,
    LOC_PLAYER_HAND,
    ConfirmedCardObservation,
)
from bot.services.ghosteek_ai.replay.models import (
    OBS_ARENA_VISIBLE,
    OBS_BATTLE_UI_VISIBLE,
    OBS_GAMEPLAY_SCREEN,
    OBS_RESULT_SCREEN,
    SOURCE_HEURISTIC,
    TimelineObservation,
)

EVENT_CARD_VISIBLE = "card_visible"
EVENT_CARD_PLAY_CANDIDATE = "card_play_candidate"
EVENT_CARD_PLAY = "card_play"
EVENT_BATTLE_STARTED = "battle_started"
EVENT_BATTLE_ENDED = "battle_ended"
EVENT_OVERTIME_STARTED = "overtime_started"
EVENT_RESULT_VISIBLE = "result_visible"

ALLOWED_EVENT_TYPES = frozenset(
    {
        EVENT_CARD_VISIBLE,
        EVENT_CARD_PLAY_CANDIDATE,
        EVENT_CARD_PLAY,
        EVENT_BATTLE_STARTED,
        EVENT_BATTLE_ENDED,
        EVENT_OVERTIME_STARTED,
        EVENT_RESULT_VISIBLE,
    }
)

PLAYER_SELF = "player"
PLAYER_OPPONENT = "opponent"
PLAYER_UNKNOWN = "unknown"

CONF_AUTHORITATIVE = 0.75
CONF_CONFIRMED = 0.90

# Play transition windows (seconds)
_PLAY_MIN_GAP = 0.05
_PLAY_MAX_GAP = 6.0
_VISIBLE_GROUP_GAP = 1.5


@dataclass(frozen=True)
class EventEvidence:
    frame_indices: tuple[int, ...]
    observation_ids: tuple[str, ...]
    timestamps: tuple[float, ...]

    def to_dict(self) -> dict:
        return {
            "frame_indices": [int(i) for i in self.frame_indices],
            "observation_ids": list(self.observation_ids),
            "timestamps": [round(float(t), 3) for t in self.timestamps],
        }


@dataclass(frozen=True)
class ReplayEvent:
    timestamp_seconds: float
    event_type: str
    player: str
    card_id: str | None
    confidence: float
    source: str
    evidence: EventEvidence

    def __post_init__(self) -> None:
        if self.event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"unknown event_type: {self.event_type}")
        if self.player not in {PLAYER_SELF, PLAYER_OPPONENT, PLAYER_UNKNOWN}:
            raise ValueError(f"unknown player: {self.player}")

    def to_dict(self) -> dict:
        return {
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "event_type": self.event_type,
            "player": self.player,
            "card_id": self.card_id,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "evidence": self.evidence.to_dict(),
        }


def observation_id(obs: ConfirmedCardObservation) -> str:
    return (
        f"card:{int(obs.frame_index)}:{obs.card_id}:"
        f"{round(float(obs.timestamp_seconds), 3)}:{obs.location}"
    )


def location_to_player(location: str) -> str:
    if location == LOC_PLAYER_HAND:
        return PLAYER_SELF
    if location == LOC_OPPONENT_HAND:
        return PLAYER_OPPONENT
    return PLAYER_UNKNOWN


class ReplayEventDetector:
    """
    Build structured events from confirmed card observations + timeline.

    card_visible ≠ card_played. Play candidates require hand → gone → arena evidence.
    Ambiguous / low-confidence inputs are ignored.
    """

    def detect(
        self,
        *,
        card_observations: Sequence[ConfirmedCardObservation] = (),
        timeline: Sequence[TimelineObservation] = (),
        ambiguous_present: bool = False,
    ) -> list[ReplayEvent]:
        del ambiguous_present  # ambiguous never become events; flag reserved for callers
        events: list[ReplayEvent] = []
        events.extend(self._card_visible_events(card_observations))
        candidates = self._card_play_candidates(card_observations)
        confirmed_plays = self._confirmed_card_plays(card_observations)
        # Drop candidates that were promoted to confirmed for the same card/player.
        confirmed_keys = {(e.card_id, e.player) for e in confirmed_plays}
        events.extend(confirmed_plays)
        events.extend(
            c for c in candidates if (c.card_id, c.player) not in confirmed_keys
        )
        events.extend(self._battle_lifecycle_events(timeline))
        # overtime_started: no Stage 3/5A overtime signal — never invent
        events = [e for e in events if float(e.confidence) >= CONF_AUTHORITATIVE]
        events.sort(
            key=lambda e: (
                e.timestamp_seconds,
                e.event_type,
                e.card_id or "",
                e.player,
            )
        )
        return events

    def partition(
        self, events: Sequence[ReplayEvent]
    ) -> tuple[list[ReplayEvent], list[ReplayEvent]]:
        """Return (all authoritative events, confirmed_events only)."""
        all_events = [e for e in events if float(e.confidence) >= CONF_AUTHORITATIVE]
        confirmed = [
            e
            for e in all_events
            if float(e.confidence) >= CONF_CONFIRMED
            and e.event_type != EVENT_CARD_PLAY_CANDIDATE
        ]
        return all_events, confirmed

    def _card_visible_events(
        self, observations: Sequence[ConfirmedCardObservation]
    ) -> list[ReplayEvent]:
        if not observations:
            return []
        ordered = sorted(
            observations,
            key=lambda o: (o.card_id, o.location, o.timestamp_seconds, o.frame_index),
        )
        groups: list[list[ConfirmedCardObservation]] = []
        cur: list[ConfirmedCardObservation] = [ordered[0]]
        for obs in ordered[1:]:
            prev = cur[-1]
            same = obs.card_id == prev.card_id and obs.location == prev.location
            close = (obs.timestamp_seconds - prev.timestamp_seconds) <= _VISIBLE_GROUP_GAP
            if same and close:
                cur.append(obs)
                continue
            groups.append(cur)
            cur = [obs]
        groups.append(cur)

        out: list[ReplayEvent] = []
        for group in groups:
            first = group[0]
            conf = max(float(o.confidence) for o in group)
            if conf < CONF_AUTHORITATIVE:
                continue
            evidence = _evidence_from(group)
            out.append(
                ReplayEvent(
                    timestamp_seconds=float(first.timestamp_seconds),
                    event_type=EVENT_CARD_VISIBLE,
                    player=location_to_player(first.location),
                    card_id=first.card_id,
                    confidence=conf,
                    source=SOURCE_HEURISTIC,
                    evidence=evidence,
                )
            )
        return out

    def _card_play_candidates(
        self, observations: Sequence[ConfirmedCardObservation]
    ) -> list[ReplayEvent]:
        if not observations:
            return []
        by_card: dict[str, list[ConfirmedCardObservation]] = {}
        for obs in observations:
            by_card.setdefault(obs.card_id, []).append(obs)

        out: list[ReplayEvent] = []
        for card_id, items in by_card.items():
            items = sorted(items, key=lambda o: (o.timestamp_seconds, o.frame_index))
            for hand_loc, player in (
                (LOC_PLAYER_HAND, PLAYER_SELF),
                (LOC_OPPONENT_HAND, PLAYER_OPPONENT),
            ):
                hand = [o for o in items if o.location == hand_loc]
                arena = [o for o in items if o.location == LOC_PLAYED_AREA]
                if not hand or not arena:
                    continue
                streaks = _streaks(hand)
                for streak in streaks:
                    last_hand = streak[-1]
                    if not _has_gap_after_hand(items, last_hand, hand_loc):
                        continue
                    arena_hit = _first_arena_after(arena, last_hand.timestamp_seconds)
                    if arena_hit is None:
                        continue
                    gap = arena_hit.timestamp_seconds - last_hand.timestamp_seconds
                    if gap < _PLAY_MIN_GAP or gap > _PLAY_MAX_GAP:
                        continue
                    conf = min(float(last_hand.confidence), float(arena_hit.confidence))
                    if gap > 3.0:
                        conf = min(conf, 0.84)
                    else:
                        conf = min(conf, 0.89)
                    if conf < CONF_AUTHORITATIVE:
                        continue
                    used = list(streak) + [arena_hit]
                    out.append(
                        ReplayEvent(
                            timestamp_seconds=float(arena_hit.timestamp_seconds),
                            event_type=EVENT_CARD_PLAY_CANDIDATE,
                            player=player,
                            card_id=card_id,
                            confidence=conf,
                            source=SOURCE_HEURISTIC,
                            evidence=_evidence_from(used),
                        )
                    )
        return _dedupe_play_candidates(out)

    def _confirmed_card_plays(
        self, observations: Sequence[ConfirmedCardObservation]
    ) -> list[ReplayEvent]:
        """
        Confirmed card_play requires independent evidence:

        1) card available in hand (HIGH);
        2) hand changes / disappears (gap);
        3) matching object in played area (HIGH);
        4) timestamps aligned.

        Missing any critical signal → not confirmed (candidate path may still fire).
        Never: card_visible alone → card_play.
        """
        if not observations:
            return []
        by_card: dict[str, list[ConfirmedCardObservation]] = {}
        for obs in observations:
            by_card.setdefault(obs.card_id, []).append(obs)

        out: list[ReplayEvent] = []
        for card_id, items in by_card.items():
            items = sorted(items, key=lambda o: (o.timestamp_seconds, o.frame_index))
            for hand_loc, player in (
                (LOC_PLAYER_HAND, PLAYER_SELF),
                (LOC_OPPONENT_HAND, PLAYER_OPPONENT),
            ):
                hand = [
                    o
                    for o in items
                    if o.location == hand_loc and float(o.confidence) >= CONF_CONFIRMED
                ]
                arena = [
                    o
                    for o in items
                    if o.location == LOC_PLAYED_AREA and float(o.confidence) >= CONF_CONFIRMED
                ]
                if len(hand) < 2 or not arena:
                    continue
                streaks = _streaks(hand)
                for streak in streaks:
                    if len(streak) < 2:
                        continue
                    last_hand = streak[-1]
                    if not _has_gap_after_hand(items, last_hand, hand_loc):
                        continue
                    arena_hit = _first_arena_after(arena, last_hand.timestamp_seconds)
                    if arena_hit is None:
                        continue
                    gap = arena_hit.timestamp_seconds - last_hand.timestamp_seconds
                    if gap < _PLAY_MIN_GAP or gap > _PLAY_MAX_GAP:
                        continue
                    # All four signals present → allow confirmed confidence.
                    conf = min(
                        float(last_hand.confidence),
                        float(arena_hit.confidence),
                        float(streak[0].confidence),
                        0.96,
                    )
                    if gap > 3.0:
                        conf = min(conf, 0.91)
                    if conf < CONF_CONFIRMED:
                        continue
                    used = list(streak) + [arena_hit]
                    out.append(
                        ReplayEvent(
                            timestamp_seconds=float(arena_hit.timestamp_seconds),
                            event_type=EVENT_CARD_PLAY,
                            player=player,
                            card_id=card_id,
                            confidence=conf,
                            source=SOURCE_HEURISTIC,
                            evidence=_evidence_from(used),
                        )
                    )
        return _dedupe_play_events(out, event_type=EVENT_CARD_PLAY)

    def _battle_lifecycle_events(
        self, timeline: Sequence[TimelineObservation]
    ) -> list[ReplayEvent]:
        if not timeline:
            return []
        start_types = {OBS_GAMEPLAY_SCREEN, OBS_ARENA_VISIBLE, OBS_BATTLE_UI_VISIBLE}
        starts = [
            t
            for t in timeline
            if t.observation_type in start_types and float(t.confidence) >= CONF_AUTHORITATIVE
        ]
        results = [
            t
            for t in timeline
            if t.observation_type == OBS_RESULT_SCREEN
            and float(t.confidence) >= CONF_AUTHORITATIVE
        ]
        out: list[ReplayEvent] = []
        if starts:
            first = min(starts, key=lambda t: (t.timestamp_seconds, t.frame_index))
            out.append(
                ReplayEvent(
                    timestamp_seconds=float(first.timestamp_seconds),
                    event_type=EVENT_BATTLE_STARTED,
                    player=PLAYER_UNKNOWN,
                    card_id=None,
                    confidence=float(first.confidence),
                    source=SOURCE_HEURISTIC,
                    evidence=EventEvidence(
                        frame_indices=(int(first.frame_index),),
                        observation_ids=(f"timeline:{first.frame_index}:{first.observation_type}",),
                        timestamps=(float(first.timestamp_seconds),),
                    ),
                )
            )
        if results:
            first_r = min(results, key=lambda t: (t.timestamp_seconds, t.frame_index))
            evidence = EventEvidence(
                frame_indices=(int(first_r.frame_index),),
                observation_ids=(f"timeline:{first_r.frame_index}:{first_r.observation_type}",),
                timestamps=(float(first_r.timestamp_seconds),),
            )
            out.append(
                ReplayEvent(
                    timestamp_seconds=float(first_r.timestamp_seconds),
                    event_type=EVENT_RESULT_VISIBLE,
                    player=PLAYER_UNKNOWN,
                    card_id=None,
                    confidence=float(first_r.confidence),
                    source=SOURCE_HEURISTIC,
                    evidence=evidence,
                )
            )
            out.append(
                ReplayEvent(
                    timestamp_seconds=float(first_r.timestamp_seconds),
                    event_type=EVENT_BATTLE_ENDED,
                    player=PLAYER_UNKNOWN,
                    card_id=None,
                    confidence=float(first_r.confidence),
                    source=SOURCE_HEURISTIC,
                    evidence=evidence,
                )
            )
        return out


def _evidence_from(obs_list: Sequence[ConfirmedCardObservation]) -> EventEvidence:
    frames = tuple(sorted({int(o.frame_index) for o in obs_list}))
    ids = tuple(observation_id(o) for o in obs_list)
    stamps = tuple(sorted({round(float(o.timestamp_seconds), 3) for o in obs_list}))
    return EventEvidence(frame_indices=frames, observation_ids=ids, timestamps=stamps)


def _streaks(hand: list[ConfirmedCardObservation]) -> list[list[ConfirmedCardObservation]]:
    if not hand:
        return []
    ordered = sorted(hand, key=lambda o: (o.timestamp_seconds, o.frame_index))
    groups: list[list[ConfirmedCardObservation]] = []
    cur = [ordered[0]]
    for obs in ordered[1:]:
        prev = cur[-1]
        if (obs.timestamp_seconds - prev.timestamp_seconds) <= _VISIBLE_GROUP_GAP:
            cur.append(obs)
            continue
        groups.append(cur)
        cur = [obs]
    groups.append(cur)
    return groups


def _has_gap_after_hand(
    all_items: Sequence[ConfirmedCardObservation],
    last_hand: ConfirmedCardObservation,
    hand_loc: str,
) -> bool:
    """
    Require temporal room after last hand sighting before a play can be inferred.

    Adjacent same-frame hand+arena is insufficient. Need a later frame_index where
    the card is no longer observed in that hand (arena counts as left-hand).
    """
    later = [
        o
        for o in all_items
        if o.frame_index > last_hand.frame_index
        and o.timestamp_seconds >= last_hand.timestamp_seconds
    ]
    if not later:
        return False
    # Still glued to hand on every later frame for this card → no transition
    later_frames = sorted({int(o.frame_index) for o in later})
    for frame_i in later_frames:
        on_frame = [o for o in later if o.frame_index == frame_i and o.card_id == last_hand.card_id]
        if not on_frame:
            return True
        if any(o.location != hand_loc for o in on_frame):
            return True
        # only hand on this frame — keep scanning
    return False


def _first_arena_after(
    arena: Sequence[ConfirmedCardObservation], after_ts: float
) -> ConfirmedCardObservation | None:
    later = [o for o in arena if o.timestamp_seconds > after_ts]
    if not later:
        return None
    return min(later, key=lambda o: (o.timestamp_seconds, o.frame_index))


def _dedupe_play_candidates(events: list[ReplayEvent]) -> list[ReplayEvent]:
    return _dedupe_play_events(events, event_type=EVENT_CARD_PLAY_CANDIDATE)


def _dedupe_play_events(events: list[ReplayEvent], *, event_type: str) -> list[ReplayEvent]:
    best: dict[tuple[str | None, str], ReplayEvent] = {}
    for ev in events:
        if ev.event_type != event_type:
            continue
        key = (ev.card_id, ev.player)
        prev = best.get(key)
        if prev is None or ev.confidence > prev.confidence:
            best[key] = ev
            continue
        if ev.confidence == prev.confidence and ev.timestamp_seconds < prev.timestamp_seconds:
            best[key] = ev
    return list(best.values())
