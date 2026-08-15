"""Grounded game event extraction: confirmed / candidate / thresholds / no hallucination."""

from __future__ import annotations

from pathlib import Path

from bot.services.ghosteek_ai.replay.card_recognizer import (
    LOC_PLAYED_AREA,
    LOC_PLAYER_HAND,
    LOC_UNKNOWN,
    ConfirmedCardObservation,
)
from bot.services.ghosteek_ai.replay.events import (
    CONF_CARD_IDENTITY_CONFIRMED,
    CONF_CARD_PLAY_CONFIRMED,
    EVENT_ARENA_VISIBLE,
    EVENT_BATTLE_END,
    EVENT_BATTLE_START,
    EVENT_CARD_BAR_VISIBLE,
    EVENT_CARD_IDENTITY_VISIBLE,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_PLAY_CONFIRMED,
    EVENT_ELIXIR_HUD_VISIBLE,
    EVENT_UNKNOWN,
    PLAYER_SELF,
    ReplayEvent,
    ReplayEventDetector,
)
from bot.services.ghosteek_ai.replay.facts import (
    LIMITATION_CARD_PLAY_UNCONFIRMED,
    ReplayFactsBuilder,
)
from bot.services.ghosteek_ai.replay.models import (
    OBS_ARENA_VISIBLE,
    OBS_CARD_BAR_VISIBLE,
    OBS_ELIXIR_HUD_VISIBLE,
    OBS_GAMEPLAY_SCREEN,
    ReplayDetection,
    TimelineObservation,
)

HOG = "26000000"
WITCH = "26000007"
FAKE_CARD = "99999999"


def _obs(
    card_id: str,
    name: str,
    conf: float,
    frame: int,
    ts: float,
    location: str,
) -> ConfirmedCardObservation:
    return ConfirmedCardObservation(
        card_id=card_id,
        card_name=name,
        confidence=conf,
        frame_index=frame,
        timestamp_seconds=ts,
        location=location,
    )


def _tl(
    ts: float,
    frame: int,
    otype: str,
    conf: float,
) -> TimelineObservation:
    return TimelineObservation(
        timestamp_seconds=ts,
        frame_index=frame,
        observation_type=otype,
        confidence=conf,
    )


def test_confirmed_event_card_identity() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.94, 0, 32.4, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.93, 1, 32.7, LOC_PLAYER_HAND),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    _, confirmed, candidates = ReplayEventDetector().partition(events)
    identities = [e for e in confirmed if e.event_type == EVENT_CARD_IDENTITY_VISIBLE]
    assert len(identities) == 1
    assert identities[0].timestamp_seconds == 32.4
    assert identities[0].confidence >= CONF_CARD_IDENTITY_CONFIRMED
    assert identities[0].evidence_frame_indexes
    assert identities[0].source == "heuristic"
    assert candidates == []


def test_candidate_event_card_play() -> None:
    # Single hand sighting → cannot confirm; weak gap path → candidate only.
    observations = [
        _obs(HOG, "Hog Rider", 0.88, 0, 34.0, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.9, 1, 34.5, LOC_UNKNOWN),
        _obs(HOG, "Hog Rider", 0.87, 2, 35.1, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    _, confirmed, candidates = ReplayEventDetector().partition(events)
    assert any(e.event_type == EVENT_CARD_PLAY_CANDIDATE for e in candidates)
    assert all(e.confidence < CONF_CARD_PLAY_CONFIRMED for e in candidates)
    assert all(e.event_type != EVENT_CARD_PLAY_CONFIRMED for e in confirmed)
    cand = next(e for e in candidates if e.event_type == EVENT_CARD_PLAY_CANDIDATE)
    assert cand.timestamp_seconds == 35.1
    assert cand.details.get("confirmed") is False


def test_below_threshold_not_confirmed() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.82, 0, 10.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.81, 1, 10.3, LOC_PLAYER_HAND),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    _, confirmed, _ = ReplayEventDetector().partition(events)
    # Authoritative band may keep identity in events, but never confirmed < 0.90
    assert all(e.confidence >= CONF_CARD_IDENTITY_CONFIRMED for e in confirmed)
    assert all(
        e.event_type != EVENT_CARD_PLAY_CONFIRMED
        or e.confidence >= CONF_CARD_PLAY_CONFIRMED
        for e in confirmed
    )
    identities = [e for e in events if e.event_type == EVENT_CARD_IDENTITY_VISIBLE]
    assert identities
    assert all(e.confidence < CONF_CARD_IDENTITY_CONFIRMED for e in identities)
    assert not any(e.event_type == EVENT_CARD_IDENTITY_VISIBLE for e in confirmed)


def test_no_evidence_no_invented_events() -> None:
    events = ReplayEventDetector().detect(card_observations=[], timeline=[])
    assert events == []
    result = ReplayFactsBuilder().build(
        ReplayDetection(status="cr_replay", confidence=0.9, frames_analyzed=8),
        [],
        duration_seconds=45.0,
        events=[],
        confirmed_events=[],
        candidate_events=[],
    )
    assert result is not None
    assert result.confirmed_events == []
    assert result.candidate_events == []
    assert LIMITATION_CARD_PLAY_UNCONFIRMED in result.limitations


def test_duplicate_play_events_collapsed() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 10.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.94, 1, 10.4, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.93, 2, 10.8, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.96, 3, 11.2, LOC_PLAYED_AREA),
        # Second arena hit — should not create a second confirmed play for same card/player
        _obs(HOG, "Hog Rider", 0.95, 4, 11.6, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    plays = [
        e
        for e in events
        if e.event_type == EVENT_CARD_PLAY_CONFIRMED and e.card_id == HOG
    ]
    assert len(plays) == 1


def test_timestamp_ordering() -> None:
    timeline = [
        _tl(40.0, 3, OBS_ELIXIR_HUD_VISIBLE, 0.92),
        _tl(1.0, 0, OBS_GAMEPLAY_SCREEN, 0.95),
        _tl(12.0, 1, OBS_ARENA_VISIBLE, 0.93),
        _tl(5.0, 0, OBS_CARD_BAR_VISIBLE, 0.91),
    ]
    observations = [
        _obs(HOG, "Hog Rider", 0.94, 2, 20.0, LOC_PLAYER_HAND),
    ]
    events = ReplayEventDetector().detect(
        card_observations=observations,
        timeline=timeline,
    )
    stamps = [e.timestamp_seconds for e in events]
    assert stamps == sorted(stamps)
    assert events[0].timestamp_seconds <= events[-1].timestamp_seconds


def test_hallucinated_card_prevention() -> None:
    """No card id appears unless present in confirmed observations."""
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 1.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.94, 1, 1.3, LOC_PLAYER_HAND),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    card_ids = {e.card_id for e in events if e.card_id}
    assert card_ids <= {HOG}
    assert FAKE_CARD not in card_ids
    assert WITCH not in card_ids
    # Visibility alone never invents a play
    assert all(e.event_type != EVENT_CARD_PLAY_CONFIRMED for e in events)


def test_card_bar_visible_is_not_play_confirmed() -> None:
    timeline = [_tl(10.0, 0, OBS_CARD_BAR_VISIBLE, 0.96)]
    events = ReplayEventDetector().detect(timeline=timeline)
    types = {e.event_type for e in events}
    assert EVENT_CARD_BAR_VISIBLE in types
    assert EVENT_CARD_PLAY_CONFIRMED not in types
    assert EVENT_CARD_PLAY_CANDIDATE not in types


def test_visibility_events_from_timeline() -> None:
    timeline = [
        _tl(2.0, 0, OBS_ARENA_VISIBLE, 0.94),
        _tl(3.0, 1, OBS_ELIXIR_HUD_VISIBLE, 0.91),
        _tl(4.0, 2, OBS_CARD_BAR_VISIBLE, 0.93),
    ]
    events = ReplayEventDetector().detect(timeline=timeline)
    types = {e.event_type for e in events}
    assert EVENT_ARENA_VISIBLE in types
    assert EVENT_ELIXIR_HUD_VISIBLE in types
    assert EVENT_CARD_BAR_VISIBLE in types
    _, confirmed, _ = ReplayEventDetector().partition(events)
    assert all(e.confidence >= 0.90 for e in confirmed)


def test_limitation_generation_for_candidates() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.88, 0, 34.0, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.9, 1, 34.5, LOC_UNKNOWN),
        _obs(HOG, "Hog Rider", 0.87, 2, 35.1, LOC_PLAYED_AREA),
    ]
    detector = ReplayEventDetector()
    raw = detector.detect(card_observations=observations)
    events, confirmed, candidates = detector.partition(raw)
    result = ReplayFactsBuilder().build(
        ReplayDetection(status="cr_replay", confidence=0.9, frames_analyzed=3),
        [_tl(1.0, 0, OBS_GAMEPLAY_SCREEN, 0.9)],
        duration_seconds=45.0,
        events=events,
        confirmed_events=confirmed,
        candidate_events=candidates,
    )
    assert result is not None
    assert result.candidate_events
    assert all(e.event_type == EVENT_CARD_PLAY_CANDIDATE for e in result.candidate_events)
    assert LIMITATION_CARD_PLAY_UNCONFIRMED in result.limitations
    payload = result.to_dict()
    assert "candidate_events" in payload
    assert payload["candidate_events"][0]["event_type"] == EVENT_CARD_PLAY_CANDIDATE
    assert "evidence_frame_indexes" in payload["candidate_events"][0]
    assert "details" in payload["candidate_events"][0]


def test_confirmed_play_requires_threshold() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 10.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.94, 1, 10.4, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.93, 2, 10.8, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.92, 3, 11.2, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    plays = [e for e in events if e.event_type == EVENT_CARD_PLAY_CONFIRMED]
    assert len(plays) == 1
    assert plays[0].confidence >= CONF_CARD_PLAY_CONFIRMED
    assert plays[0].details.get("confirmed") is True


def test_replay_event_schema_fields() -> None:
    ev = ReplayEvent(
        timestamp_seconds=32.4,
        event_type=EVENT_CARD_IDENTITY_VISIBLE,
        player=PLAYER_SELF,
        card_id=HOG,
        confidence=0.94,
        source="heuristic",
        evidence=__import__(
            "bot.services.ghosteek_ai.replay.events", fromlist=["EventEvidence"]
        ).EventEvidence(
            frame_indices=(4,),
            observation_ids=("card:4:x",),
            timestamps=(32.4,),
        ),
        details={"card_id": HOG},
    )
    d = ev.to_dict()
    assert d["timestamp_seconds"] == 32.4
    assert d["event_type"] == EVENT_CARD_IDENTITY_VISIBLE
    assert d["confidence"] == 0.94
    assert d["source"] == "heuristic"
    assert d["evidence_frame_indexes"] == [4]
    assert isinstance(d["details"], dict)


def test_legacy_event_type_normalized() -> None:
    from bot.services.ghosteek_ai.replay.events import EventEvidence

    ev = ReplayEvent(
        timestamp_seconds=1.0,
        event_type="card_play",
        player=PLAYER_SELF,
        card_id=HOG,
        confidence=0.95,
        source="heuristic",
        evidence=EventEvidence(frame_indices=(0,), observation_ids=("a",), timestamps=(1.0,)),
    )
    assert ev.event_type == EVENT_CARD_PLAY_CONFIRMED


def test_battle_lifecycle_grounded_names() -> None:
    from bot.services.ghosteek_ai.replay.models import OBS_RESULT_SCREEN

    timeline = [
        _tl(1.0, 0, OBS_GAMEPLAY_SCREEN, 0.95),
        _tl(50.0, 5, OBS_RESULT_SCREEN, 0.94),
    ]
    events = ReplayEventDetector().detect(timeline=timeline)
    types = {e.event_type for e in events}
    assert EVENT_BATTLE_START in types
    assert EVENT_BATTLE_END in types
    assert EVENT_UNKNOWN not in types  # not invented without OBS_UNKNOWN


def test_no_llm_in_grounded_modules() -> None:
    import bot.services.ghosteek_ai.replay.events as events_mod
    import bot.services.ghosteek_ai.replay.facts as facts_mod

    for mod in (events_mod, facts_mod):
        src = Path(mod.__file__).read_text(encoding="utf-8").lower()
        assert "qwen" not in src
        assert "ollama" not in src
        assert "raw video" not in src
