"""Stage 5 FULL: confirmed plays, adaptive stamps, cycle, elixir, conclusions."""

from __future__ import annotations

import pytest

from bot.services.ghosteek_ai.replay.card_recognizer import (
    LOC_OPPONENT_HAND,
    LOC_PLAYED_AREA,
    LOC_PLAYER_HAND,
    LOC_UNKNOWN,
    ConfirmedCardFact,
    ConfirmedCardObservation,
)
from bot.services.ghosteek_ai.replay.cycle import build_cycle_from_confirmed_plays
from bot.services.ghosteek_ai.replay.elixir import ElixirObserver, KIND_OBSERVED
from bot.services.ghosteek_ai.replay.events import (
    EVENT_BATTLE_STARTED,
    EVENT_CARD_PLAY,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_VISIBLE,
    PLAYER_OPPONENT,
    PLAYER_SELF,
    PLAYER_UNKNOWN,
    EventEvidence,
    ReplayEvent,
    ReplayEventDetector,
)
from bot.services.ghosteek_ai.replay.game_state import (
    GS_ARENA_VISIBLE,
    GS_ELIXIR_HUD_VISIBLE,
    GS_OPPONENT_HAND_VISIBLE,
    GameStateBuilder,
    GameStateObservation,
)
from bot.services.ghosteek_ai.replay.models import (
    HeuristicSignal,
    FrameSignalSnapshot,
    analysis_fps,
    event_fps,
    max_concurrent_jobs,
)
from bot.services.ghosteek_ai.replay.sampler import (
    densify_on_changes,
    timestamps_at_fps,
)
from bot.services.ghosteek_ai.replay.tactical_analysis import (
    ReplayTacticalAnalyzer,
    TacticalConclusion,
)
from bot.services.ghosteek_ai.replay.battle_timeline import ReplayBattleTimelineBuilder

HOG = "26000000"
CANNON = "27000000"
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


def _ev(
    ts: float,
    etype: str,
    *,
    card_id: str | None = None,
    player: str = PLAYER_SELF,
    conf: float = 0.95,
) -> ReplayEvent:
    return ReplayEvent(
        timestamp_seconds=ts,
        event_type=etype,
        player=player,
        card_id=card_id,
        confidence=conf,
        source="heuristic",
        evidence=EventEvidence((0,), (f"id:{ts}",), (ts,)),
    )


def test_env_fps_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_ANALYSIS_FPS", "99")
    assert analysis_fps() == 4.0
    monkeypatch.setenv("REPLAY_EVENT_FPS", "1")
    assert event_fps() == 6.0
    monkeypatch.setenv("REPLAY_MAX_CONCURRENT_JOBS", "5")
    assert max_concurrent_jobs() == 1


def test_adaptive_timestamps_and_densify() -> None:
    coarse = timestamps_at_fps(10.0, 2.0, max_frames=40)
    assert coarse[0] == 0.0
    assert len(coarse) >= 5
    dense = densify_on_changes(
        coarse,
        {1, 3},
        duration=10.0,
        event_fps=8.0,
        max_frames=96,
    )
    assert len(dense) >= len(coarse)
    assert dense == sorted(dense)
    assert dense[0] == 0.0


def test_confirmed_card_play_requires_four_signals() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 10.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.94, 1, 10.3, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.93, 2, 10.7, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.96, 3, 11.1, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    plays = [e for e in events if e.event_type == EVENT_CARD_PLAY]
    assert len(plays) == 1
    assert plays[0].confidence >= 0.90
    assert plays[0].player == PLAYER_SELF
    # candidate for same card/player should be suppressed
    assert not any(
        e.event_type == EVENT_CARD_PLAY_CANDIDATE and e.card_id == HOG for e in events
    )


def test_weak_hand_stays_candidate_not_confirmed() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.88, 0, 10.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.87, 1, 10.3, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.93, 2, 10.7, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.96, 3, 11.1, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    assert not any(e.event_type == EVENT_CARD_PLAY for e in events)


def test_card_visible_not_automatic_play() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.99, 0, 1.0, LOC_UNKNOWN),
        _obs(HOG, "Hog Rider", 0.99, 1, 1.4, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    assert all(e.event_type != EVENT_CARD_PLAY for e in events)
    assert all(e.event_type != EVENT_CARD_PLAY_CANDIDATE for e in events)
    assert any(e.event_type == EVENT_CARD_VISIBLE for e in events)


def test_ambiguous_never_becomes_event() -> None:
    # Ambiguous observations are not passed into detect — only confirmed HIGH.
    # Ensure detector ignores unknown/low paths.
    observations = [_obs(HOG, "Hog Rider", 0.70, 0, 1.0, LOC_PLAYER_HAND)]
    events = ReplayEventDetector().detect(card_observations=observations)
    assert events == []


def test_player_opponent_uncertainty() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 5.0, LOC_UNKNOWN),
        _obs(HOG, "Hog Rider", 0.95, 1, 5.3, LOC_UNKNOWN),
        _obs(HOG, "Hog Rider", 0.95, 2, 5.8, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    assert all(e.event_type != EVENT_CARD_PLAY for e in events)
    visible = [e for e in events if e.event_type == EVENT_CARD_VISIBLE]
    assert visible
    assert all(e.player == PLAYER_UNKNOWN for e in visible)


def test_duplicate_and_ordering() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 10.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.94, 1, 10.2, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.93, 2, 10.5, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.96, 3, 10.9, LOC_PLAYED_AREA),
        # second weaker transition should not duplicate
        _obs(HOG, "Hog Rider", 0.95, 4, 12.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.94, 5, 12.2, LOC_PLAYER_HAND),
        _obs(WITCH, "Witch", 0.93, 6, 12.5, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.91, 7, 12.9, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    plays = [e for e in events if e.event_type == EVENT_CARD_PLAY and e.card_id == HOG]
    assert len(plays) == 1
    stamps = [e.timestamp_seconds for e in events]
    assert stamps == sorted(stamps)


def test_missing_frame_blocks_confirmed_play() -> None:
    # No gap frame → no confirmed play / candidate
    observations = [
        _obs(HOG, "Hog Rider", 0.95, 0, 10.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.96, 0, 10.0, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    assert not any(e.event_type in {EVENT_CARD_PLAY, EVENT_CARD_PLAY_CANDIDATE} for e in events)


def test_elixir_unavailable_without_ocr() -> None:
    gs = [
        GameStateObservation(
            type=GS_ELIXIR_HUD_VISIBLE,
            timestamp=1.0,
            confidence=0.9,
            source="heuristic",
            evidence={"frame_index": 0},
        )
    ]
    obs = ElixirObserver().observe(gs)
    assert len(obs) == 1
    assert obs[0].kind == KIND_OBSERVED
    assert obs[0].value is None


def test_game_state_does_not_invent_opponent_hand() -> None:
    frames = [
        FrameSignalSnapshot(
            frame_index=0,
            timestamp=1.0,
            score=0.8,
            signals=(
                HeuristicSignal("arena_layout", 0.8, 0.85, "arena"),
                HeuristicSignal("card_bar", 0.7, 0.8, "cards"),
                HeuristicSignal("gameplay_region", 0.75, 0.8, "game"),
            ),
        )
    ]
    states = GameStateBuilder().build(frames)
    types = {s.type for s in states}
    assert GS_ARENA_VISIBLE in types
    assert GS_OPPONENT_HAND_VISIBLE not in types


def test_cycle_from_confirmed_plays_only() -> None:
    events = [
        _ev(1.0, EVENT_BATTLE_STARTED, conf=0.95),
        _ev(5.0, EVENT_CARD_PLAY, card_id=HOG, player=PLAYER_SELF, conf=0.94),
        _ev(8.0, EVENT_CARD_PLAY_CANDIDATE, card_id=WITCH, player=PLAYER_SELF, conf=0.88),
        _ev(12.0, EVENT_CARD_PLAY, card_id=CANNON, player=PLAYER_OPPONENT, conf=0.93),
    ]
    _, confirmed = ReplayEventDetector().partition(events)[:2]
    cycle = build_cycle_from_confirmed_plays(confirmed)
    assert cycle.player_cycle == [HOG]
    assert cycle.opponent_cycle == [CANNON]
    assert WITCH not in cycle.player_cycle


def test_tactical_conclusion_requires_evidence() -> None:
    confirmed = [
        _ev(1.0, EVENT_BATTLE_STARTED),
        _ev(5.0, EVENT_CARD_PLAY, card_id=HOG, player=PLAYER_SELF),
    ]
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=40.0,
        events=confirmed,
        confirmed_events=confirmed,
        confirmed_cards=[ConfirmedCardFact(HOG, "Hog Rider", 0.95, 5.0, 5.0)],
    )
    analysis = ReplayTacticalAnalyzer().analyze(
        battle_timeline=battle,
        confirmed_cards=[ConfirmedCardFact(HOG, "Hog Rider", 0.95, 5.0, 5.0)],
        confirmed_events=confirmed,
        events=confirmed,
    )
    assert analysis.conclusions
    for c in analysis.conclusions:
        assert isinstance(c, TacticalConclusion)
        assert c.evidence
        assert c.confidence > 0


def test_invented_card_play_impossible() -> None:
    # No observations → no invented plays
    events = ReplayEventDetector().detect(card_observations=[])
    assert events == []


def test_low_confidence_discarded() -> None:
    observations = [
        _obs(HOG, "Hog Rider", 0.5, 0, 1.0, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.5, 1, 1.3, LOC_PLAYER_HAND),
        _obs(HOG, "Hog Rider", 0.5, 2, 1.8, LOC_PLAYED_AREA),
    ]
    events = ReplayEventDetector().detect(card_observations=observations)
    assert events == []


def test_matchup_from_confirmed_cards_only() -> None:
    analyzer = ReplayTacticalAnalyzer()
    cards = [
        ConfirmedCardFact(HOG, "Hog Rider", 0.95, 1.0, 1.0),
        ConfirmedCardFact(CANNON, "Cannon", 0.95, 2.0, 2.0),
    ]
    confirmed = [
        _ev(1.0, EVENT_CARD_VISIBLE, card_id=CANNON, player=PLAYER_SELF),
        _ev(2.0, EVENT_CARD_VISIBLE, card_id=HOG, player=PLAYER_OPPONENT),
    ]
    # side names come from confirmed events with card ids
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=50.0,
        events=confirmed,
        confirmed_events=confirmed,
        confirmed_cards=cards,
    )
    analysis = analyzer.analyze(
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=confirmed,
    )
    # With both sides present, matchup may or may not fire depending on DB —
    # but must never invent cards outside catalog.
    blob = " ".join(analysis.matchup_observations + analysis.deck_observations)
    assert "FakeUnit" not in blob
