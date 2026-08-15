"""Stage 4: timeline + facts from Stage 3 signals. No card events, no Qwen."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.responses import JSONResponse

from bot.api.routes import ai as ai_routes
from bot.api.schemas import GhosteekAiAskRequest
from bot.services.ghosteek_ai.models import GhosteekAiResponse
from bot.services.ghosteek_ai.replay.facts import ReplayFactsBuilder
from bot.services.ghosteek_ai.replay.models import (
    DEFAULT_LIMITATIONS,
    OBS_ARENA_VISIBLE,
    OBS_CARD_BAR_VISIBLE,
    OBS_ELIXIR_HUD_VISIBLE,
    OBS_GAMEPLAY_SCREEN,
    DetectionBundle,
    FrameSignalSnapshot,
    HeuristicSignal,
    ReplayDetection,
    TimelineObservation,
)
from bot.services.ghosteek_ai.replay.service import ReplayAnalyzeService
from bot.services.ghosteek_ai.replay.timeline import ReplayTimelineBuilder

MP4_HEADER = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32


def _sig(name: str, score: float = 0.84, confidence: float = 0.78) -> HeuristicSignal:
    return HeuristicSignal(name, score, confidence, f"{name} detected")


def _frame(index: int, ts: float, *signals: HeuristicSignal, score: float = 0.8) -> FrameSignalSnapshot:
    return FrameSignalSnapshot(frame_index=index, timestamp=ts, score=score, signals=signals)


def test_timeline_from_observations() -> None:
    frames = [
        _frame(0, 0.0, _sig("gameplay_region"), _sig("card_bar")),
        _frame(1, 10.5, _sig("arena_layout"), _sig("elixir_hud")),
    ]
    timeline = ReplayTimelineBuilder().build(frames)
    types = {item.observation_type for item in timeline}
    assert OBS_GAMEPLAY_SCREEN in types
    assert OBS_CARD_BAR_VISIBLE in types
    assert OBS_ARENA_VISIBLE in types
    assert OBS_ELIXIR_HUD_VISIBLE in types


def test_timeline_keeps_timestamp_frame_index_confidence() -> None:
    frames = [_frame(7, 42.5, _sig("card_bar", 0.9, 0.8))]
    timeline = ReplayTimelineBuilder().build(frames)
    assert len(timeline) == 1
    item = timeline[0]
    assert item.timestamp_seconds == 42.5
    assert item.frame_index == 7
    assert item.confidence == pytest.approx(0.72, abs=0.001)
    assert item.source == "heuristic"


def test_unknown_observation_type_rejected() -> None:
    with pytest.raises(ValueError):
        TimelineObservation(
            timestamp_seconds=1.0,
            frame_index=0,
            observation_type="player_played_hog_rider",
            confidence=0.9,
        )


def test_facts_no_invented_card_events() -> None:
    detection = ReplayDetection(status="cr_replay", confidence=0.91, frames_analyzed=20)
    timeline = [
        TimelineObservation(1.0, 0, OBS_GAMEPLAY_SCREEN, 0.8),
        TimelineObservation(1.0, 0, OBS_CARD_BAR_VISIBLE, 0.8),
        TimelineObservation(2.0, 1, OBS_ELIXIR_HUD_VISIBLE, 0.8),
        TimelineObservation(3.0, 2, OBS_ARENA_VISIBLE, 0.8),
    ]
    # Pad arena hits across frames for "consistently"
    for i in range(3, 10):
        timeline.append(TimelineObservation(float(i), i, OBS_ARENA_VISIBLE, 0.7))
    result = ReplayFactsBuilder().build(detection, timeline, duration_seconds=187.4)
    assert result is not None
    joined = " ".join(result.facts).lower()
    for banned in ("hog", "witch", "fireball", "golem", "damage", "played"):
        assert banned not in joined
    assert "card_play_events_not_detected" in result.limitations
    assert set(DEFAULT_LIMITATIONS).issubset(set(result.limitations))


def test_limitations_always_present_for_cr() -> None:
    detection = ReplayDetection(status="cr_replay", confidence=0.9, frames_analyzed=16)
    result = ReplayFactsBuilder().build(detection, [], duration_seconds=40.0)
    assert result is not None
    assert result.limitations
    assert "elixir_values_not_extracted" in result.limitations
    assert "deck_identity_not_confirmed" in result.limitations


def test_uncertain_and_not_cr_have_no_facts() -> None:
    builder = ReplayFactsBuilder()
    for status in ("uncertain", "not_cr_replay"):
        detection = ReplayDetection(status=status, confidence=0.4, frames_analyzed=20)
        assert builder.build(detection, [], duration_seconds=10.0) is None


def _ok_probe(_path: Path) -> tuple[float, int, int, float | None]:
    return 187.4, 1920, 1080, 60.0


def _fake_upload(filename: str, data: bytes, content_type: str | None) -> SimpleNamespace:
    state = {"off": 0}

    async def read(n: int = -1) -> bytes:
        off = state["off"]
        chunk = data[off:] if n is None or n < 0 else data[off : off + n]
        state["off"] = off + len(chunk)
        return chunk

    async def close() -> None:
        return None

    return SimpleNamespace(filename=filename, content_type=content_type, read=read, close=close)


def _call_analyze(monkeypatch, detection: ReplayDetection, frames=()):
    service = ReplayAnalyzeService()
    monkeypatch.setattr("bot.services.ghosteek_ai.replay.service.probe_video", _ok_probe)
    monkeypatch.setattr(
        ReplayAnalyzeService,
        "_run_detection",
        lambda self, *args, **kwargs: DetectionBundle(detection=detection, frames=tuple(frames)),
    )
    monkeypatch.setattr(ai_routes, "get_replay_service", lambda: service)

    async def _run():
        return await ai_routes.analyze_replay(
            user=MagicMock(telegram_id=1),
            file=_fake_upload("battle.mp4", MP4_HEADER, "video/mp4"),  # type: ignore[arg-type]
        )

    return asyncio.run(_run())


def test_api_cr_includes_replay_facts(monkeypatch) -> None:
    frames = [
        _frame(0, 0.0, _sig("gameplay_region"), _sig("card_bar"), _sig("elixir_hud"), _sig("arena_layout")),
        _frame(1, 5.0, _sig("card_bar"), _sig("elixir_hud"), _sig("arena_layout")),
    ]
    result = _call_analyze(
        monkeypatch,
        ReplayDetection(status="cr_replay", confidence=0.91, frames_analyzed=2, observations=["card bar detected"]),
        frames=frames,
    )
    payload = result.model_dump()
    assert payload["status"] == "cr_replay"
    assert payload["replay_facts"] is not None
    assert payload["replay_facts"]["source"] == "replay_analysis"
    assert payload["replay_facts"]["timeline"]
    assert payload["replay_facts"]["facts"]
    assert payload["replay_facts"]["limitations"]
    assert payload["replay_facts"]["frames_analyzed"] == 2


def test_api_uncertain_no_fake_facts(monkeypatch) -> None:
    result = _call_analyze(
        monkeypatch,
        ReplayDetection(status="uncertain", confidence=0.48, frames_analyzed=20),
    )
    assert result.model_dump()["replay_facts"] is None


def test_api_not_cr_no_fake_facts(monkeypatch) -> None:
    result = _call_analyze(
        monkeypatch,
        ReplayDetection(status="not_cr_replay", confidence=0.12, frames_analyzed=20),
    )
    assert result.model_dump()["replay_facts"] is None


def test_ask_untouched(monkeypatch) -> None:
    async def _fake_ask(message: str, user, context=None):
        del user, context
        return GhosteekAiResponse(intent="chat", answer=f"echo:{message}", sources={"ok": True})

    monkeypatch.setattr(ai_routes, "ask_ghosteek_ai", _fake_ask)
    body = GhosteekAiAskRequest(message="привет")

    async def _run():
        return await ai_routes.ask_ai(body, user=MagicMock())

    result = asyncio.run(_run())
    assert result.intent == "chat"
    assert result.answer == "echo:привет"


def test_regression_no_card_names_in_facts() -> None:
    detection = ReplayDetection(status="cr_replay", confidence=0.95, frames_analyzed=20)
    timeline = []
    for i in range(20):
        timeline.append(TimelineObservation(float(i), i, OBS_CARD_BAR_VISIBLE, 0.8))
        timeline.append(TimelineObservation(float(i), i, OBS_ELIXIR_HUD_VISIBLE, 0.8))
        timeline.append(TimelineObservation(float(i), i, OBS_ARENA_VISIBLE, 0.8))
        timeline.append(TimelineObservation(float(i), i, OBS_GAMEPLAY_SCREEN, 0.8))
    result = ReplayFactsBuilder().build(detection, timeline, duration_seconds=100.0)
    assert result is not None
    facts_blob = " ".join(result.facts).lower()
    for token in (
        "hog rider",
        "witch",
        "fireball",
        "golem",
        "elixir value",
        "tower took",
        "card play timestamp",
    ):
        assert token not in facts_blob
    assert "damage_events_not_detected" in result.limitations
    assert "card_play_events_not_detected" in result.limitations


def test_qwen_not_invoked_in_stage4_builders() -> None:
    import bot.services.ghosteek_ai.replay.facts as facts_mod
    import bot.services.ghosteek_ai.replay.timeline as timeline_mod

    assert "qwen" not in facts_mod.__file__.lower()
    src_facts = Path(facts_mod.__file__).read_text(encoding="utf-8").lower()
    src_timeline = Path(timeline_mod.__file__).read_text(encoding="utf-8").lower()
    assert "qwen" not in src_facts
    assert "ollama" not in src_facts
    assert "qwen" not in src_timeline
    frames = [_frame(0, 1.0, _sig("card_bar"), _sig("elixir_hud"), _sig("arena_layout"))]
    detection = ReplayDetection(status="cr_replay", confidence=0.9, frames_analyzed=1)
    timeline = ReplayTimelineBuilder().build(frames)
    ReplayFactsBuilder().build(detection, timeline, duration_seconds=30.0)
