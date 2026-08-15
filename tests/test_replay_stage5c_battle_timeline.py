"""Stage 5C: chronological battle timeline from ReplayEvents. No coaching."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.services.ghosteek_ai.replay.battle_timeline import (
    PHASE_ENDING,
    PHASE_MID_GAME,
    PHASE_OPENING,
    PHASE_OVERTIME,
    ReplayBattleTimelineBuilder,
    build_confirmed_phases,
    build_unknown_intervals,
    sort_events,
)
from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact
from bot.services.ghosteek_ai.replay.events import (
    EVENT_BATTLE_ENDED,
    EVENT_BATTLE_STARTED,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_VISIBLE,
    EVENT_OVERTIME_STARTED,
    EVENT_RESULT_VISIBLE,
    EventEvidence,
    PLAYER_SELF,
    PLAYER_UNKNOWN,
    ReplayEvent,
)
from bot.services.ghosteek_ai.replay.facts import ReplayFactsBuilder
from bot.services.ghosteek_ai.replay.models import (
    OBS_GAMEPLAY_SCREEN,
    ReplayDetection,
    TimelineObservation,
)


def _ev(
    ts: float,
    event_type: str,
    *,
    conf: float = 0.95,
    card_id: str | None = None,
    player: str = PLAYER_UNKNOWN,
    frame: int = 0,
) -> ReplayEvent:
    return ReplayEvent(
        timestamp_seconds=ts,
        event_type=event_type,
        player=player,
        card_id=card_id,
        confidence=conf,
        source="heuristic",
        evidence=EventEvidence(
            frame_indices=(frame,),
            observation_ids=(f"t:{frame}:{event_type}",),
            timestamps=(ts,),
        ),
    )


def test_chronological_ordering() -> None:
    events = [
        _ev(40.0, EVENT_RESULT_VISIBLE),
        _ev(1.0, EVENT_BATTLE_STARTED),
        _ev(12.0, EVENT_CARD_VISIBLE, card_id="26000000", player=PLAYER_SELF),
    ]
    ordered = sort_events(events)
    assert [e.timestamp_seconds for e in ordered] == [1.0, 12.0, 40.0]


def test_duplicate_timestamps_tie_break() -> None:
    events = [
        _ev(10.0, EVENT_RESULT_VISIBLE, frame=2),
        _ev(10.0, EVENT_CARD_PLAY_CANDIDATE, card_id="1", conf=0.88, frame=1),
        _ev(10.0, EVENT_BATTLE_STARTED, frame=0),
    ]
    ordered = sort_events(events)
    assert [e.event_type for e in ordered] == [
        EVENT_BATTLE_STARTED,
        EVENT_CARD_PLAY_CANDIDATE,
        EVENT_RESULT_VISIBLE,
    ]


def test_unknown_intervals() -> None:
    confirmed = [
        _ev(10.0, EVENT_BATTLE_STARTED),
        _ev(35.0, EVENT_CARD_VISIBLE, card_id="26000000"),
        _ev(51.2, EVENT_RESULT_VISIBLE),
    ]
    # gap 10→35 and 35→51.2 both > 2s
    intervals = build_unknown_intervals(confirmed)
    assert len(intervals) == 2
    assert intervals[0].to_dict() == {"from": 10.0, "to": 35.0, "status": "unknown"}
    assert intervals[1].to_dict()["from"] == 35.0
    assert intervals[1].to_dict()["to"] == 51.2


def test_missing_events_no_invention() -> None:
    timeline = ReplayBattleTimelineBuilder().build(
        duration_seconds=180.0,
        events=[_ev(5.0, EVENT_BATTLE_STARTED)],
        confirmed_events=[_ev(5.0, EVENT_BATTLE_STARTED)],
    )
    types = {e.event_type for e in timeline.events}
    assert EVENT_BATTLE_ENDED not in types
    assert EVENT_RESULT_VISIBLE not in types
    assert EVENT_OVERTIME_STARTED not in types
    assert timeline.summary is not None
    assert timeline.summary.confirmed_event_count == 1


def test_uncertain_detection_no_facts_battle_timeline() -> None:
    result = ReplayFactsBuilder().build(
        ReplayDetection(status="uncertain", confidence=0.4, frames_analyzed=10),
        [],
        duration_seconds=60.0,
        events=[_ev(1.0, EVENT_BATTLE_STARTED)],
    )
    assert result is None


def test_partial_replay_summary() -> None:
    confirmed = [
        _ev(20.0, EVENT_BATTLE_STARTED),
        _ev(45.0, EVENT_CARD_VISIBLE, card_id="26000000"),
    ]
    tl = ReplayBattleTimelineBuilder().build(
        duration_seconds=200.0,
        events=confirmed,
        confirmed_events=confirmed,
        confirmed_cards=[
            ConfirmedCardFact("26000000", "Hog Rider", 0.94, 45.0, 45.0),
        ],
        confidence=0.91,
    )
    assert tl.summary is not None
    assert tl.summary.first_event == pytest.approx(20.0)
    assert tl.summary.last_event == pytest.approx(45.0)
    assert tl.summary.known_duration == pytest.approx(25.0)
    assert tl.summary.confirmed_card_count == 1
    assert tl.duration_seconds == pytest.approx(200.0)
    assert tl.confidence == pytest.approx(0.91)


def test_overtime_phase_only_when_confirmed() -> None:
    without = [
        _ev(1.0, EVENT_BATTLE_STARTED),
        _ev(50.0, EVENT_RESULT_VISIBLE),
    ]
    phases = build_confirmed_phases(without)
    phase_names = {p.phase for p in phases}
    assert PHASE_OVERTIME not in phase_names
    # Must not claim overtime was absent — simply omit the phase
    assert PHASE_OPENING in phase_names
    assert PHASE_ENDING in phase_names

    with_ot = without + [_ev(40.0, EVENT_OVERTIME_STARTED)]
    phases2 = build_confirmed_phases(with_ot)
    assert PHASE_OVERTIME in {p.phase for p in phases2}


def test_result_screen_phases() -> None:
    confirmed = [
        _ev(2.0, EVENT_BATTLE_STARTED),
        _ev(30.0, EVENT_CARD_VISIBLE, card_id="26000000"),
        _ev(90.0, EVENT_RESULT_VISIBLE),
        _ev(90.0, EVENT_BATTLE_ENDED),
    ]
    tl = ReplayBattleTimelineBuilder().build(
        duration_seconds=95.0,
        events=confirmed,
        confirmed_events=confirmed,
    )
    names = [p.phase for p in tl.phases]
    assert PHASE_OPENING in names
    assert PHASE_MID_GAME in names
    assert PHASE_ENDING in names
    assert EVENT_RESULT_VISIBLE in {e.event_type for e in tl.confirmed_events}


def test_empty_timeline() -> None:
    tl = ReplayBattleTimelineBuilder().build(duration_seconds=120.0, events=[], confirmed_events=[])
    assert tl.events == []
    assert tl.confirmed_events == []
    assert tl.unknown_intervals == []
    assert tl.phases == []
    assert tl.summary is not None
    assert tl.summary.confirmed_event_count == 0
    assert tl.summary.first_event is None
    assert tl.summary.known_duration == 0.0
    assert tl.confidence == 0.0
    payload = tl.to_dict()
    assert payload["duration_seconds"] == 120.0
    assert payload["summary"]["unknown_intervals_count"] == 0


def test_candidates_not_promoted_in_battle_timeline() -> None:
    events = [
        _ev(1.0, EVENT_BATTLE_STARTED, conf=0.95),
        _ev(10.0, EVENT_CARD_PLAY_CANDIDATE, card_id="26000000", conf=0.88),
        _ev(12.0, EVENT_CARD_VISIBLE, card_id="26000000", conf=0.94),
    ]
    confirmed = [e for e in events if e.event_type != EVENT_CARD_PLAY_CANDIDATE]
    tl = ReplayBattleTimelineBuilder().build(
        duration_seconds=60.0,
        events=events,
        confirmed_events=confirmed,
    )
    assert any(e.event_type == EVENT_CARD_PLAY_CANDIDATE for e in tl.events)
    assert all(e.event_type != EVENT_CARD_PLAY_CANDIDATE for e in tl.confirmed_events)


def test_facts_include_battle_timeline() -> None:
    events = [_ev(1.0, EVENT_BATTLE_STARTED), _ev(40.0, EVENT_RESULT_VISIBLE)]
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=50.0,
        events=events,
        confirmed_events=events,
    )
    result = ReplayFactsBuilder().build(
        ReplayDetection(status="cr_replay", confidence=0.92, frames_analyzed=8),
        [TimelineObservation(1.0, 0, OBS_GAMEPLAY_SCREEN, 0.9)],
        duration_seconds=50.0,
        events=events,
        confirmed_events=events,
        battle_timeline=battle,
    )
    assert result is not None
    assert result.battle_timeline is not None
    blob = result.to_dict()
    assert blob["battle_timeline"]["summary"]["confirmed_event_count"] == 2
    joined = " ".join(result.facts).lower()
    assert "should have" not in joined
    assert "mistake" not in joined


def test_no_llm_in_battle_timeline_module() -> None:
    import bot.services.ghosteek_ai.replay.battle_timeline as mod

    src = Path(mod.__file__).read_text(encoding="utf-8").lower()
    assert "qwen" not in src
    assert "ollama" not in src
