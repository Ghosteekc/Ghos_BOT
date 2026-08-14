"""Replay follow-up: accepted CR meta is remembered; coaching Stage 4 still pending."""

from __future__ import annotations

from bot.services.ghosteek_ai.replay_followup import (
    is_replay_coaching_request,
    normalize_replay_meta,
    reply_replay_pending_analysis,
    resolve_replay_meta,
)


def test_is_replay_coaching_request() -> None:
    assert is_replay_coaching_request("Какие мои ошибки в этом видео?")
    assert is_replay_coaching_request("разбери этот реплей")
    assert not is_replay_coaching_request("собери колоду hog")


def test_reply_mentions_seen_replay_not_missing() -> None:
    meta = normalize_replay_meta(
        {
            "status": "cr_replay",
            "filename": "battle.mp4",
            "duration_seconds": 45.2,
            "width": 720,
            "height": 1560,
            "confidence": 0.9,
        }
    )
    assert meta is not None
    text = reply_replay_pending_analysis(meta)
    low = text.lower()
    assert "вижу" in low or "реплей" in low
    assert "не вижу" not in low
    assert "0:45" in text or "45" in text


def test_resolve_prefers_request_over_session() -> None:
    session = {"status": "uncertain", "filename": "old.mp4", "duration_seconds": 10, "width": 1, "height": 1}
    request = {
        "replay": {
            "status": "cr_replay",
            "filename": "new.mp4",
            "duration_seconds": 45,
            "width": 720,
            "height": 1560,
        }
    }
    meta = resolve_replay_meta(session, request)
    assert meta is not None
    assert meta["status"] == "cr_replay"
    assert meta["filename"] == "new.mp4"
