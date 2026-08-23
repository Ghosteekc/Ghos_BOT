"""Stage 6: Evidence Frames + Visual Moments — grounded vision → real frames only."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.api.routes.ai import _public_visual_moment
from bot.api.schemas import ReplayFactsResponse
from bot.services.ghosteek_ai.replay.evidence import (
    EvidenceBuilder,
    EvidenceFrame,
    EvidenceStore,
    ReplayVisualMoment,
    _clamp,
    _nearest_sampled_frame,
    get_evidence_store,
)
from bot.services.ghosteek_ai.replay.models import (
    OBS_CARD_PLAY_CANDIDATE,
    OBS_CARD_VISIBLE,
    OBS_UNKNOWN,
    STATUS_CR,
    FrameSignalSnapshot,
    ReplayAnalysisResult,
)
from bot.services.ghosteek_ai.replay.vision_analyzer import VisionObservation


def _obs(
    ts: float,
    frame_index: int,
    event_type: str = OBS_CARD_VISIBLE,
    *,
    confidence: float = 0.94,
    card_name: str | None = "Hog Rider",
) -> VisionObservation:
    return VisionObservation(
        timestamp_seconds=ts,
        frame_index=frame_index,
        event_type=event_type,
        confidence=confidence,
        card_name=card_name,
    )


def _frame(index: int, ts: float) -> FrameSignalSnapshot:
    return FrameSignalSnapshot(frame_index=index, timestamp=ts, score=0.8)


@pytest.fixture(autouse=True)
def _enable_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_EVIDENCE_ENABLED", "1")
    monkeypatch.setenv("REPLAY_EVIDENCE_CLIP_ENABLED", "0")


@pytest.fixture
def store() -> EvidenceStore:
    s = EvidenceStore(ttl_seconds=60, max_items=32)
    return s


def _fake_jpeg_extract(monkeypatch: pytest.MonkeyPatch, *, succeed: bool = True) -> list[float]:
    calls: list[float] = []

    def fake_extract(*, binary, video_path, timestamp, dest, width, height) -> bool:
        del binary, video_path, width, height
        calls.append(float(timestamp))
        if not succeed:
            return False
        dest.write_bytes(b"\xff\xd8\xff\xe0" + b"jpeg-fake" + b"\xff\xd9")
        return True

    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.evidence._extract_jpeg",
        fake_extract,
    )
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.evidence.find_ffmpeg",
        lambda: "ffmpeg",
    )
    return calls


def test_confirmed_vision_event_creates_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    calls = _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-mp4")
    builder = EvidenceBuilder(store=store, confidence_threshold=0.9, max_moments=6)
    moments = builder.build(
        video_path=video,
        duration_seconds=60.0,
        src_width=1080,
        src_height=1920,
        vision_observations=[_obs(42.5, 7)],
        sampled_frames=[_frame(7, 42.5)],
    )
    assert len(moments) == 1
    m = moments[0]
    assert m.event_type == OBS_CARD_VISIBLE
    assert m.card_name == "Hog Rider"
    assert m.confidence == pytest.approx(0.94)
    assert m.source == "vision"
    assert m.clip_available is False
    assert m.evidence_id
    assert m.preview_base64
    assert m.evidence_frame.frame_index == 7
    assert m.evidence_frame.timestamp_seconds == pytest.approx(42.5)
    assert m.evidence_frame.path is None
    assert calls == [42.5]
    public = m.to_dict()
    assert "path" not in public["evidence_frame"]
    assert store.get(m.evidence_id) is not None


def test_candidate_event_no_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store).build(
        video_path=video,
        duration_seconds=30.0,
        src_width=720,
        src_height=1280,
        vision_observations=[
            _obs(10.0, 3, OBS_CARD_PLAY_CANDIDATE, confidence=0.99),
        ],
        sampled_frames=[_frame(3, 10.0)],
    )
    assert moments == []


def test_unknown_no_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store).build(
        video_path=video,
        duration_seconds=30.0,
        src_width=720,
        src_height=1280,
        vision_observations=[_obs(10.0, 3, OBS_UNKNOWN, confidence=0.99, card_name=None)],
        sampled_frames=[_frame(3, 10.0)],
    )
    assert moments == []


def test_nearest_frame_chosen_correctly() -> None:
    obs = _obs(10.4, 99)
    frames = [_frame(1, 8.0), _frame(2, 10.0), _frame(3, 12.0)]
    nearest = _nearest_sampled_frame(obs, frames)
    assert nearest is not None
    assert nearest.frame_index == 2
    assert nearest.timestamp == pytest.approx(10.0)

    exact = _nearest_sampled_frame(_obs(10.0, 2), frames)
    assert exact is not None
    assert exact.frame_index == 2


def test_duplicate_events_deduped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    obs = [
        _obs(42.0, 7, confidence=0.95),
        _obs(42.8, 8, confidence=0.93),  # within 1.5s window, same card
        _obs(50.0, 9, confidence=0.92),
    ]
    moments = EvidenceBuilder(store=store, dedupe_window_seconds=1.5).build(
        video_path=video,
        duration_seconds=80.0,
        src_width=1080,
        src_height=1920,
        vision_observations=obs,
        sampled_frames=[_frame(7, 42.0), _frame(8, 42.8), _frame(9, 50.0)],
    )
    assert len(moments) == 2
    assert [m.timestamp_seconds for m in moments] == [42.0, 50.0]


def test_max_six_moments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    obs = [_obs(float(i * 5), i, confidence=0.95) for i in range(10)]
    frames = [_frame(i, float(i * 5)) for i in range(10)]
    moments = EvidenceBuilder(store=store, max_moments=6).build(
        video_path=video,
        duration_seconds=120.0,
        src_width=1080,
        src_height=1920,
        vision_observations=obs,
        sampled_frames=frames,
    )
    assert len(moments) == 6


def test_timestamp_near_start_clamped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    calls = _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store).build(
        video_path=video,
        duration_seconds=60.0,
        src_width=1080,
        src_height=1920,
        vision_observations=[_obs(0.2, 0)],
        sampled_frames=[_frame(0, 0.0), _frame(1, 5.0)],
    )
    assert len(moments) == 1
    assert moments[0].evidence_frame.timestamp_seconds == pytest.approx(0.0)
    assert calls[0] == pytest.approx(0.0)


def test_timestamp_near_end_clamped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    calls = _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store).build(
        video_path=video,
        duration_seconds=100.0,
        src_width=1080,
        src_height=1920,
        vision_observations=[_obs(99.7, 20)],
        sampled_frames=[_frame(18, 95.0), _frame(19, 99.0)],
    )
    assert len(moments) == 1
    assert moments[0].evidence_frame.frame_index == 19
    assert moments[0].evidence_frame.timestamp_seconds == pytest.approx(99.0)
    assert calls[0] == pytest.approx(99.0)
    assert _clamp(101.0, 0.0, 100.0) == 100.0


def test_clip_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    _fake_jpeg_extract(monkeypatch)
    clip_calls: list[float] = []

    def fake_clip(**kwargs) -> bool:
        clip_calls.append(float(kwargs["center_ts"]))
        return True

    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.evidence._extract_clip",
        fake_clip,
    )
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store, clip_enabled=False).build(
        video_path=video,
        duration_seconds=40.0,
        src_width=720,
        src_height=1280,
        vision_observations=[_obs(12.0, 4)],
        sampled_frames=[_frame(4, 12.0)],
    )
    assert len(moments) == 1
    assert moments[0].clip_available is False
    assert moments[0].clip_id is None
    assert clip_calls == []


def test_clip_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    _fake_jpeg_extract(monkeypatch)

    def fake_clip(*, binary, video_path, center_ts, duration_seconds, pre_seconds, post_seconds, dest, width, height) -> bool:
        del binary, video_path, center_ts, duration_seconds, pre_seconds, post_seconds, width, height
        dest.write_bytes(b"RIFF" + b"webp-fake")
        return True

    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.evidence._extract_clip",
        fake_clip,
    )
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store, clip_enabled=True).build(
        video_path=video,
        duration_seconds=40.0,
        src_width=720,
        src_height=1280,
        vision_observations=[_obs(12.0, 4)],
        sampled_frames=[_frame(4, 12.0)],
    )
    assert len(moments) == 1
    assert moments[0].clip_available is True
    assert moments[0].clip_id
    assert store.get(moments[0].clip_id) is not None


def test_cleanup_temp_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    job_dir = tmp_path / "evidence-job"
    job_dir.mkdir()
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.evidence.tempfile.mkdtemp",
        lambda prefix="": str(job_dir),
    )
    _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    EvidenceBuilder(store=store).build(
        video_path=video,
        duration_seconds=20.0,
        src_width=720,
        src_height=1280,
        vision_observations=[_obs(5.0, 1)],
        sampled_frames=[_frame(1, 5.0)],
    )
    assert not job_dir.exists()


def test_invalid_frame_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    _fake_jpeg_extract(monkeypatch, succeed=False)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store).build(
        video_path=video,
        duration_seconds=20.0,
        src_width=720,
        src_height=1280,
        vision_observations=[_obs(5.0, 1)],
        sampled_frames=[_frame(1, 5.0)],
    )
    assert moments == []


def test_missing_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    monkeypatch.setattr(
        "bot.services.ghosteek_ai.replay.evidence.find_ffmpeg",
        lambda: None,
    )
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store).build(
        video_path=video,
        duration_seconds=20.0,
        src_width=720,
        src_height=1280,
        vision_observations=[_obs(5.0, 1)],
        sampled_frames=[_frame(1, 5.0)],
    )
    assert moments == []


def test_api_does_not_expose_filesystem_paths() -> None:
    payload = {
        "event_type": "card_visible",
        "timestamp_seconds": 42.5,
        "card_name": "Hog Rider",
        "confidence": 0.94,
        "evidence_frame": {
            "timestamp_seconds": 42.5,
            "frame_index": 7,
            "path": "/tmp/secret/frame.jpg",
            "width": 720,
            "height": 1280,
        },
        "evidence_id": "opaque-token",
        "clip_id": None,
        "clip_available": False,
        "preview_base64": "abc",
        "source": "vision",
        "clip_path": "/tmp/secret/clip.webp",
    }
    public = _public_visual_moment(payload)
    blob = str(public)
    assert "/tmp" not in blob
    assert "path" not in public["evidence_frame"]
    assert "clip_path" not in public
    assert public["evidence_id"] == "opaque-token"

    frame = EvidenceFrame(7, 42.5, path="/abs/secret.jpg", width=720, height=1280)
    assert "path" not in frame.to_public_dict()

    store = get_evidence_store()
    assert store.get("../../etc/passwd") is None
    assert store.get("C:\\Windows\\system32") is None


def test_replay_facts_visual_moments_serialize() -> None:
    moment = ReplayVisualMoment(
        event_type=OBS_CARD_VISIBLE,
        timestamp_seconds=42.5,
        confidence=0.94,
        card_name="Hog Rider",
        evidence_frame=EvidenceFrame(7, 42.5, path=None, width=720, height=1280),
        evidence_id="tok1",
        preview_base64="YmFzZTY0",
        clip_available=False,
    )
    result = ReplayAnalysisResult(
        status=STATUS_CR,
        confidence=0.9,
        duration_seconds=180.0,
        frames_analyzed=24,
        visual_moments=[moment],
    )
    payload = result.to_dict()
    assert "visual_moments" in payload
    assert len(payload["visual_moments"]) == 1
    vm = payload["visual_moments"][0]
    assert vm["event_type"] == "card_visible"
    assert vm["evidence_frame"]["frame_index"] == 7
    assert "path" not in vm["evidence_frame"]

    validated = ReplayFactsResponse.model_validate(
        {
            **payload,
            "replay_status": payload["replay_status"],
        }
    )
    assert len(validated.visual_moments) == 1
    assert validated.visual_moments[0].clip_available is False


def test_low_confidence_below_threshold_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store, confidence_threshold=0.90).build(
        video_path=video,
        duration_seconds=30.0,
        src_width=720,
        src_height=1280,
        vision_observations=[_obs(10.0, 2, confidence=0.85)],
        sampled_frames=[_frame(2, 10.0)],
    )
    assert moments == []


def test_evidence_disabled_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, store: EvidenceStore
) -> None:
    monkeypatch.setenv("REPLAY_EVIDENCE_ENABLED", "0")
    _fake_jpeg_extract(monkeypatch)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    moments = EvidenceBuilder(store=store).build(
        video_path=video,
        duration_seconds=30.0,
        src_width=720,
        src_height=1280,
        vision_observations=[_obs(10.0, 2)],
        sampled_frames=[_frame(2, 10.0)],
    )
    assert moments == []


def test_frontend_empty_visual_moments_payload_shape() -> None:
    """Empty visual_moments must remain a list so FE can render grounded summary."""
    result = ReplayAnalysisResult(
        status=STATUS_CR,
        confidence=0.8,
        duration_seconds=60.0,
        frames_analyzed=12,
        visual_moments=[],
    )
    payload = result.to_dict()
    assert payload["visual_moments"] == []
    validated = ReplayFactsResponse.model_validate(payload)
    assert validated.visual_moments == []
