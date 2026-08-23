"""Stage 5: Vision Event Analyzer — observations only, no coaching."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog, CatalogCard
from bot.services.ghosteek_ai.replay.candidate_frames import CandidateFrameSelector
from bot.services.ghosteek_ai.replay.events import (
    EVENT_CARD_PLAY_CANDIDATE,
    EventEvidence,
    ReplayEvent,
)
from bot.services.ghosteek_ai.replay.facts import ReplayFactsBuilder
from bot.services.ghosteek_ai.replay.models import (
    OBS_CARD_BAR_VISIBLE,
    SOURCE_VISION,
    STATUS_CR,
    DetectionBundle,
    FrameSignalSnapshot,
    HeuristicSignal,
    ReplayDetection,
    TimelineObservation,
    replay_event_confidence_threshold,
    vision_enabled,
    vision_max_frames_per_job,
)
from bot.services.ghosteek_ai.replay.ollama_vision_analyzer import (
    OllamaVisionAnalyzer,
    OllamaVisionTimeout,
    OllamaVisionUnavailable,
    _parse_json_content,
)
from bot.services.ghosteek_ai.replay.service import ReplayAnalyzeService
from bot.services.ghosteek_ai.replay.timeline import ReplayTimelineBuilder
from bot.services.ghosteek_ai.replay.vision_analyzer import (
    NullVisionAnalyzer,
    VisionAnalyzer,
    VisionObservation,
)
from bot.services.ghosteek_ai.replay.vision_events import (
    merge_timeline_with_vision,
    parse_raw_observations,
    partition_vision_observations,
    repartition_merged_events,
    vision_observations_to_events,
)

HOG_ID = "26000000"


def _catalog() -> CardCatalog:
    return CardCatalog((CatalogCard(card_id=HOG_ID, card_name="Hog Rider"),))


def _sig(name: str, score: float = 0.84) -> HeuristicSignal:
    return HeuristicSignal(name, score, 0.78, f"{name} detected")


def _frame(
    index: int,
    ts: float,
    *signals: HeuristicSignal,
    score: float = 0.8,
) -> FrameSignalSnapshot:
    return FrameSignalSnapshot(
        frame_index=index,
        timestamp=ts,
        score=score,
        signals=signals,
    )


class MockVisionAnalyzer(VisionAnalyzer):
    def __init__(
        self,
        responses: dict[int, list[VisionObservation]] | None = None,
    ) -> None:
        self._responses = responses or {}
        self.calls: list[tuple[str, int, float]] = []

    async def analyze_frame(
        self,
        frame_path: str,
        *,
        frame_index: int,
        timestamp_seconds: float,
    ) -> list[VisionObservation]:
        self.calls.append((frame_path, frame_index, timestamp_seconds))
        return list(self._responses.get(frame_index, []))


def test_vision_analyzer_interface() -> None:
    assert issubclass(MockVisionAnalyzer, VisionAnalyzer)
    assert issubclass(NullVisionAnalyzer, VisionAnalyzer)
    assert (
        asyncio.run(
            NullVisionAnalyzer().analyze_frame(
                "x.jpg",
                frame_index=0,
                timestamp_seconds=0.0,
            )
        )
        == []
    )


def test_valid_structured_response() -> None:
    payload = {
        "observations": [
            {
                "event_type": "troop_visible",
                "card_name": "Hog Rider",
                "side": "player",
                "lane": "right",
                "confidence": 0.91,
            }
        ]
    }
    obs = parse_raw_observations(
        payload,
        frame_index=3,
        timestamp_seconds=42.5,
        catalog=_catalog(),
    )
    assert len(obs) == 1
    assert obs[0].event_type == "troop_visible"
    assert obs[0].card_name == "Hog Rider"
    assert obs[0].card_id == HOG_ID
    assert obs[0].confidence == pytest.approx(0.91)


def test_malformed_response_returns_empty() -> None:
    assert parse_raw_observations({"observations": "nope"}, frame_index=0, timestamp_seconds=0.0) == []
    assert parse_raw_observations([{"event_type": 123}], frame_index=0, timestamp_seconds=0.0) == []
    assert _parse_json_content("not json") is None


def test_unknown_card_name_becomes_null() -> None:
    payload = {
        "observations": [
            {"event_type": "troop_visible", "card_name": "Fake Card XYZ", "confidence": 0.95}
        ]
    }
    obs = parse_raw_observations(payload, frame_index=0, timestamp_seconds=1.0, catalog=_catalog())
    assert len(obs) == 1
    assert obs[0].card_name is None
    assert obs[0].card_id is None


def test_unknown_event_type_rejected() -> None:
    payload = {"observations": [{"event_type": "player_misplay", "confidence": 0.99}]}
    assert parse_raw_observations(payload, frame_index=0, timestamp_seconds=0.0) == []


def test_low_confidence_stays_candidate() -> None:
    obs = VisionObservation(
        timestamp_seconds=10.0,
        frame_index=1,
        event_type="troop_visible",
        confidence=0.82,
        card_name="Hog Rider",
        card_id=HOG_ID,
    )
    confirmed, candidates = partition_vision_observations([obs], threshold=0.90)
    assert confirmed == []
    assert candidates == [obs]


def test_confidence_threshold_confirms() -> None:
    obs = VisionObservation(
        timestamp_seconds=10.0,
        frame_index=1,
        event_type="troop_visible",
        confidence=0.91,
        card_name="Hog Rider",
        card_id=HOG_ID,
    )
    confirmed, candidates = partition_vision_observations([obs], threshold=0.90)
    assert candidates == []
    assert confirmed == [obs]


def test_no_hallucinated_card_when_low_confidence() -> None:
    payload = {
        "observations": [
            {"event_type": "card_visible", "card_name": "Hog Rider", "confidence": 0.55}
        ]
    }
    obs = parse_raw_observations(payload, frame_index=0, timestamp_seconds=0.0, catalog=_catalog())
    assert len(obs) == 1
    assert obs[0].card_name is None


def test_candidate_to_confirmed_via_repartition() -> None:
    low = ReplayEvent(
        timestamp_seconds=5.0,
        event_type=EVENT_CARD_PLAY_CANDIDATE,
        player="player",
        card_id=HOG_ID,
        confidence=0.85,
        source=SOURCE_VISION,
        evidence=EventEvidence((1,), ("v:1",), (5.0,)),
        details={"card_name": "Hog Rider"},
    )
    high = ReplayEvent(
        timestamp_seconds=6.0,
        event_type="troop_visible",
        player="player",
        card_id=HOG_ID,
        confidence=0.92,
        source=SOURCE_VISION,
        evidence=EventEvidence((2,), ("v:2",), (6.0,)),
        details={"card_name": "Hog Rider"},
    )
    all_e, confirmed, candidates = repartition_merged_events([low, high], threshold=0.90)
    assert low in all_e
    assert high in confirmed
    assert any(c.event_type == EVENT_CARD_PLAY_CANDIDATE for c in candidates)


def test_timeline_integration() -> None:
    heuristic = [
        TimelineObservation(0.0, 0, OBS_CARD_BAR_VISIBLE, 0.8, source="heuristic"),
    ]
    vision = VisionObservation(
        timestamp_seconds=42.5,
        frame_index=7,
        event_type="troop_visible",
        confidence=0.91,
        card_name="Hog Rider",
        card_id=HOG_ID,
    )
    merged = merge_timeline_with_vision(heuristic, [vision])
    assert len(merged) == 2
    vision_row = [x for x in merged if x.source == SOURCE_VISION][0]
    assert vision_row.frame_index == 7
    assert vision_row.observation_type == "troop_visible"


def test_facts_integration_vision_grounded() -> None:
    detection = ReplayDetection(status=STATUS_CR, confidence=0.9, frames_analyzed=10)
    timeline = [TimelineObservation(0.0, 0, OBS_CARD_BAR_VISIBLE, 0.8)]
    confirmed_event = ReplayEvent(
        timestamp_seconds=42.5,
        event_type="troop_visible",
        player="player",
        card_id=HOG_ID,
        confidence=0.91,
        source=SOURCE_VISION,
        evidence=EventEvidence((7,), ("vision:7",), (42.5,)),
        details={"card_name": "Hog Rider"},
    )
    result = ReplayFactsBuilder().build(
        detection,
        timeline,
        duration_seconds=90.0,
        confirmed_events=[confirmed_event],
        events=[confirmed_event],
    )
    assert result is not None
    assert "Vision confirmed Hog Rider visibility at 42.5s." in result.facts
    assert not any("bad moment" in f.lower() for f in result.facts)


def test_candidate_frame_selector_respects_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_VISION_MAX_FRAMES_PER_JOB", "4")
    monkeypatch.setenv("REPLAY_VISION_MIN_FRAME_GAP_SECONDS", "1.0")
    frames = [
        _frame(0, 0.0, _sig("card_bar", 0.5)),
        _frame(1, 0.5, _sig("card_bar", 0.9)),
        _frame(2, 1.5, _sig("arena_layout", 0.9)),
        _frame(3, 3.0, _sig("arena_layout", 0.4)),
        _frame(4, 5.0, _sig("elixir_hud", 0.9)),
    ]
    picked = CandidateFrameSelector(max_frames=vision_max_frames_per_job()).select(
        frames, duration_seconds=10.0
    )
    assert len(picked) <= 4
    for a, b in zip(picked, picked[1:]):
        assert b.timestamp_seconds - a.timestamp_seconds >= 1.0 or len(picked) == 1


def test_ollama_timeout_returns_empty(tmp_path: Path) -> None:
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
    analyzer = OllamaVisionAnalyzer(base_url="http://127.0.0.1:9", timeout_seconds=0.01)

    async def _run() -> list[VisionObservation]:
        with patch.object(analyzer, "_post_chat", side_effect=OllamaVisionTimeout("timeout")):
            return await analyzer.analyze_frame(str(frame), frame_index=0, timestamp_seconds=0.0)

    assert asyncio.run(_run()) == []


def test_ollama_unavailable_returns_empty(tmp_path: Path) -> None:
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
    analyzer = OllamaVisionAnalyzer(base_url="http://127.0.0.1:9", timeout_seconds=1.0)

    async def _run() -> list[VisionObservation]:
        with patch.object(analyzer, "_post_chat", side_effect=OllamaVisionUnavailable("down")):
            return await analyzer.analyze_frame(str(frame), frame_index=0, timestamp_seconds=0.0)

    assert asyncio.run(_run()) == []


def test_replay_pipeline_without_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_VISION_ENABLED", "0")
    assert vision_enabled() is False
    service = ReplayAnalyzeService(vision_analyzer=MockVisionAnalyzer())
    frames = [_frame(0, 0.0, _sig("card_bar"))]
    bundle = DetectionBundle(
        detection=ReplayDetection(status=STATUS_CR, confidence=0.9, frames_analyzed=1),
        frames=tuple(frames),
        confirmed_card_observations=(),
        ambiguous_card_observations=(),
        game_state_observations=(),
        vision_observations=(),
    )
    analysis = service._build_stage4(bundle, duration_seconds=60.0)  # noqa: SLF001
    assert analysis is not None
    assert all(item.source != SOURCE_VISION for item in analysis.timeline)


def test_build_from_bundle_merges_vision() -> None:
    frames = (_frame(0, 0.0, _sig("card_bar")),)
    vision = (
        VisionObservation(
            timestamp_seconds=1.0,
            frame_index=0,
            event_type="spell_visible",
            confidence=0.93,
        ),
    )
    bundle = DetectionBundle(
        detection=ReplayDetection(status=STATUS_CR, confidence=0.9, frames_analyzed=1),
        frames=frames,
        vision_observations=vision,
    )
    timeline = ReplayTimelineBuilder().build_from_bundle(bundle)
    assert any(
        x.observation_type == "spell_visible" and x.source == SOURCE_VISION for x in timeline
    )


def test_vision_events_to_replay_events() -> None:
    obs = VisionObservation(
        timestamp_seconds=3.0,
        frame_index=2,
        event_type="building_visible",
        confidence=0.88,
    )
    events = vision_observations_to_events([obs])
    assert len(events) == 1
    assert events[0].source == SOURCE_VISION


def test_env_confidence_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_EVENT_CONFIDENCE_THRESHOLD", "0.95")
    assert replay_event_confidence_threshold() == pytest.approx(0.95)
