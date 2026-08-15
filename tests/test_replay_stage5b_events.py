"""Stage 5B: conservative replay event detection. No LLM, no invented plays."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.services.ghosteek_ai.replay.card_recognizer import (
    LOC_OPPONENT_HAND,
    LOC_PLAYED_AREA,
    LOC_PLAYER_HAND,
    LOC_UNKNOWN,
    ConfirmedCardObservation,
)
from bot.services.ghosteek_ai.replay.events import (
    EVENT_BATTLE_ENDED,
    EVENT_BATTLE_STARTED,
    EVENT_CARD_PLAY,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_VISIBLE,
    EVENT_OVERTIME_STARTED,
    EVENT_RESULT_VISIBLE,
    PLAYER_OPPONENT,
    PLAYER_SELF,
    PLAYER_UNKNOWN,
    ReplayEventDetector,
)
from bot.services.ghosteek_ai.replay.facts import ReplayFactsBuilder
from bot.services.ghosteek_ai.replay.models import (
    OBS_GAMEPLAY_SCREEN,
    OBS_RESULT_SCREEN,
    ReplayDetection,
    TimelineObservation,
)

HOG = "26000000"
WITCH = "26000007"


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


def test_hand_to_arena_transition_creates_play_candidate() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 10.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.94, 1, 10.4, LOC_PLAYER_HAND),
        # gap frame without hog in hand
        _obs(WITCH, "Witch", 0.93, 2, 10.8, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.92, 3, 11.2, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    # Stage 5 full: four independent HIGH signals promote to confirmed card_play.
    plays = [e for e in events if e.event_type == EVENT_CARD_PLAY]
    assert len(plays) == 1
    assert plays[0].card_id == HOG
    assert plays[0].player == PLAYER_SELF
    assert plays[0].confidence >= 0.90
    assert plays[0].evidence.frame_indices
    assert plays[0].evidence.observation_ids
    assert plays[0].evidence.timestamps
    # Candidate suppressed once confirmed for same card/player.
    assert not any(e.event_type == EVENT_CARD_PLAY_CANDIDATE and e.card_id == HOG for e in events)


def test_card_visible_without_play() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.94, 0, 5.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.93, 1, 5.3, LOC_PLAYER_HAND),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    types = {e.event_type for e in events}
    assert EVENT_CARD_VISIBLE in types
    assert EVENT_CARD_PLAY_CANDIDATE not in types


def test_regression_visibility_is_not_automatic_play() -> None:
    """card_visible ≠ card_played — presence alone must never invent a play."""
    observations = [
        _obs(HOG, "Hog Rider", 0.99, 0, 1.0, LOC_UNKNOWN),
        _obs(HOG, "Hog Rider", 0.99, 1, 1.4, LOC_PLAYED_AREA),
        _obs(HOG, "Hog Rider", 0.99, 2, 2.0, LOC_UNKNOWN),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    assert all(e.event_type != EVENT_CARD_PLAY_CANDIDATE for e in events)
    assert any(e.event_type == EVENT_CARD_VISIBLE for e in events)


def test_ambiguous_card_does_not_create_events() -> None:
    # Detector only receives confirmed observations; ambiguous stays out.
    events = ReplayEventDetector().detect(
        card_observations=[],
        ambiguous_present=True,
    )
    assert events == []


def test_missing_frames_no_play() -> None:
    # Hand then nothing — no arena transition evidence
    observations = [_obs(HOG, "Hog Rider", 0.95, 0, 8.0, LOC_PLAYER_HAND)]
    events = ReplayEventDetector().detect(card_observations=observations)
    assert all(e.event_type != EVENT_CARD_PLAY_CANDIDATE for e in events)


def test_duplicate_frames_grouped_visible() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.91, 0, 32.1, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.92, 1, 32.4, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.94, 2, 32.7, LOC_PLAYER_HAND),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    visibles = [e for e in events if e.event_type == EVENT_CARD_VISIBLE and e.card_id == HOG]
    assert len(visibles) == 1
    assert visibles[0].timestamp_seconds == pytest.approx(32.1)


def test_low_confidence_not_authoritative() -> None:
    observations = [_obs(HOG, "Hog Rider", 0.70, 0, 1.0, LOC_PLAYER_HAND)]
    events = ReplayEventDetector().detect(card_observations=observations)
    assert events == []


def test_multiple_cards() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.94, 0, 1.0, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.93, 0, 1.0, LOC_OPPONENT_HAND),
        _obs(WITCH, "Witch", 0.9, 1, 1.4, LOC_UNKNOWN),  # hog left hand; witch left opp hand
        _obs(HOG, "Hog Rider", 0.92, 2, 1.8, LOC_PLAYED_AREA),
        _obs(WITCH, "Witch", 0.91, 3, 2.2, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    plays = [e for e in events if e.event_type == EVENT_CARD_PLAY_CANDIDATE]
    play_ids = {e.card_id for e in plays}
    assert HOG in play_ids
    assert WITCH in play_ids


def test_player_opponent_uncertainty() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 1.0, LOC_UNKNOWN),
        _obs(HOG, "Hog Rider", 0.94, 1, 1.5, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    visibles = [e for e in events if e.event_type == EVENT_CARD_VISIBLE]
    assert all(e.player == PLAYER_UNKNOWN for e in visibles)
    assert all(e.event_type != EVENT_CARD_PLAY_CANDIDATE for e in events)

    observations2 = [
        _obs(HOG, "Hog Rider", 0.95, 0, 1.0, LOC_OPPONENT_HAND),
        _obs(WITCH, "Witch", 0.93, 1, 1.4, LOC_OPPONENT_HAND),
        _obs(HOG, "Hog Rider", 0.94, 2, 1.8, LOC_PLAYED_AREA),
    ]
    events2 = ReplayEventDetector().detect(card_observations=observations2)
    plays = [e for e in events2 if e.event_type == EVENT_CARD_PLAY_CANDIDATE]
    assert len(plays) == 1
    assert plays[0].player == PLAYER_OPPONENT


def test_event_and_timestamp_ordering() -> None:
    timeline = [
        TimelineObservation(20.0, 5, OBS_RESULT_SCREEN, 0.91),
        TimelineObservation(1.0, 0, OBS_GAMEPLAY_SCREEN, 0.92),
    ]
    observations = [
        _obs(HOG, "Hog Rider", 0.94, 1, 4.0, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.9, 2, 4.5, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.93, 3, 5.0, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(
        card_observations=observations,
        timeline=timeline,
    )
    stamps = [e.timestamp_seconds for e in events]
    assert stamps == sorted(stamps)
    types = [e.event_type for e in events]
    assert EVENT_BATTLE_STARTED in types
    assert EVENT_RESULT_VISIBLE in types
    assert EVENT_BATTLE_ENDED in types
    assert EVENT_OVERTIME_STARTED not in types


def test_candidates_not_in_confirmed_events() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 10.0, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.9, 1, 10.5, LOC_UNKNOWN),
        _obs(HOG, "Hog Rider", 0.94, 2, 11.0, LOC_PLAYED_AREA),
    ]
    detector = ReplayEventDetector()
    raw = detector.detect(card_observations=observations)
    events, confirmed = detector.partition(raw)[:2]
    assert any(e.event_type == EVENT_CARD_PLAY_CANDIDATE for e in events)
    assert all(e.event_type != EVENT_CARD_PLAY_CANDIDATE for e in confirmed)
    assert all(e.confidence >= 0.90 for e in confirmed)

    result = ReplayFactsBuilder().build(
        ReplayDetection(status="cr_replay", confidence=0.9, frames_analyzed=3),
        [TimelineObservation(1.0, 0, OBS_GAMEPLAY_SCREEN, 0.9)],
        duration_seconds=30.0,
        events=events,
        confirmed_events=confirmed,
    )
    assert result is not None
    assert any(e.event_type == EVENT_CARD_PLAY_CANDIDATE for e in result.events)
    assert all(e.event_type != EVENT_CARD_PLAY_CANDIDATE for e in result.confirmed_events)


def test_forbidden_event_types_not_emitted() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.99, 0, 1.0, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.9, 1, 1.3, LOC_UNKNOWN),
        _obs(HOG, "Hog Rider", 0.99, 2, 1.6, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    banned = {
        "damage",
        "tower_damage",
        "elixir_spent",
        "cycle",
        "misplay",
        "bad_defense",
        "good_play",
        "counter",
        "win_probability",
        "card_play",
        "card_deployed",
    }
    assert not banned.intersection({e.event_type for e in events})


def test_no_llm_in_events_module() -> None:
    import bot.services.ghosteek_ai.replay.events as events_mod

    src = Path(events_mod.__file__).read_text(encoding="utf-8").lower()
    assert "qwen" not in src
    assert "ollama" not in src
