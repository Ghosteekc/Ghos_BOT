"""Moment shot selection and extraction (no real ffmpeg required for unit tests)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact
from bot.services.ghosteek_ai.replay.events import (
    EVENT_BATTLE_START,
    EVENT_CARD_IDENTITY_VISIBLE,
    EVENT_CARD_PLAY_CANDIDATE,
    EventEvidence,
    PLAYER_SELF,
    ReplayEvent,
)
from bot.services.ghosteek_ai.replay.moment_shots import (
    MomentShot,
    _select_targets,
    extract_moment_shots,
)


def _ev(ts: float, etype: str, *, card_id: str | None = None, conf: float = 0.95) -> ReplayEvent:
    return ReplayEvent(
        timestamp_seconds=ts,
        event_type=etype,
        player=PLAYER_SELF,
        card_id=card_id,
        confidence=conf,
        source="heuristic",
        evidence=EventEvidence((0,), (f"id:{ts}",), (ts,)),
    )


def test_select_targets_prefers_confirmed_then_candidates() -> None:
    cards = [ConfirmedCardFact("26000000", "Hog Rider", 0.94, 10.0, 12.0)]
    confirmed = [
        _ev(1.0, EVENT_BATTLE_START),
        _ev(10.0, EVENT_CARD_IDENTITY_VISIBLE, card_id="26000000"),
    ]
    candidates = [_ev(15.0, EVENT_CARD_PLAY_CANDIDATE, card_id="26000000", conf=0.88)]
    targets = _select_targets(
        confirmed_events=confirmed,
        candidate_events=candidates,
        confirmed_cards=cards,
        limit=6,
    )
    assert len(targets) == 3
    assert targets[0][2] == "confirmed"
    assert targets[1][1] == "Карта на экране: Hog Rider"
    assert targets[2][2] == "candidate"


def test_select_targets_respects_limit() -> None:
    confirmed = [_ev(float(i), EVENT_BATTLE_START) for i in range(10)]
    targets = _select_targets(
        confirmed_events=confirmed,
        candidate_events=[],
        confirmed_cards=[],
        limit=6,
    )
    assert len(targets) == 6


def test_extract_moment_shots_skips_when_no_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.moment_shots.find_ffmpeg",
        lambda: None,
    )
    video = tmp_path / "x.mp4"
    video.write_bytes(b"fake")
    shots = extract_moment_shots(
        video,
        src_width=1080,
        src_height=1920,
        confirmed_events=[_ev(1.0, EVENT_BATTLE_START)],
    )
    assert shots == []


def test_extract_moment_shots_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.moment_shots.find_ffmpeg",
        lambda: "ffmpeg",
    )

    def fake_b64(**kwargs):
        del kwargs
        return "YmFzZTY0"

    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.moment_shots._extract_jpeg_b64",
        fake_b64,
    )
    video = tmp_path / "x.mp4"
    video.write_bytes(b"fake")
    shots = extract_moment_shots(
        video,
        src_width=1080,
        src_height=1920,
        confirmed_events=[_ev(2.5, EVENT_BATTLE_START)],
    )
    assert len(shots) == 1
    assert isinstance(shots[0], MomentShot)
    assert shots[0].timestamp_seconds == 2.5
    assert shots[0].image_base64 == "YmFzZTY0"
    assert shots[0].to_dict()["kind"] == "confirmed"


def test_extract_skips_failed_frame(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.moment_shots.find_ffmpeg",
        lambda: "ffmpeg",
    )
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.moment_shots._extract_jpeg_b64",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    video = tmp_path / "x.mp4"
    video.write_bytes(b"fake")
    shots = extract_moment_shots(
        video,
        src_width=1080,
        src_height=1920,
        confirmed_events=[_ev(1.0, EVENT_BATTLE_START)],
    )
    assert shots == []
