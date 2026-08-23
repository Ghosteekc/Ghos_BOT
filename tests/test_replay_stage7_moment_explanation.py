"""Stage 7: grounded moment explanation — facts SoT, Qwen wording only."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from bot.api.routes.ai import _public_visual_moment
from bot.services.ghosteek_ai.replay.evidence import EvidenceFrame, ReplayVisualMoment
from bot.services.ghosteek_ai.replay.events import EVENT_CARD_PLAY_CONFIRMED
from bot.services.ghosteek_ai.replay.models import (
    OBS_CARD_PLAY_CANDIDATE,
    OBS_CARD_VISIBLE,
    OBS_TOWER_DAMAGE_CANDIDATE,
    OBS_UNKNOWN,
)
from bot.services.ghosteek_ai.replay.moment_renderer import (
    EXPLANATION_CARD_PLAY_CONFIRMED,
    EXPLANATION_CARD_VISIBLE,
    EXPLANATION_UNKNOWN,
    ReplayMomentRenderer,
    ReplaySummaryRenderer,
    classify_explanation_kind,
    fallback_moment_explanation,
    fallback_replay_summary,
    validate_moment_explanation,
)


def _frame(ts: float = 12.0, idx: int = 3) -> EvidenceFrame:
    return EvidenceFrame(frame_index=idx, timestamp_seconds=ts, path=None, width=720, height=1280)


def _moment(
    *,
    event_type: str = OBS_CARD_VISIBLE,
    ts: float = 12.0,
    card: str | None = "Hog Rider",
    conf: float = 0.94,
) -> ReplayVisualMoment:
    return ReplayVisualMoment(
        event_type=event_type,
        timestamp_seconds=ts,
        confidence=conf,
        evidence_frame=_frame(ts),
        card_name=card,
    )


@dataclass
class _Ev:
    event_type: str
    timestamp_seconds: float
    details: dict
    card_id: str | None = None


def test_card_visible_fallback_is_neutral() -> None:
    moment = _moment(event_type=OBS_CARD_VISIBLE, card="Hog Rider")
    kind = classify_explanation_kind(moment)
    assert kind == EXPLANATION_CARD_VISIBLE
    expl = fallback_moment_explanation(moment, kind=kind)
    assert "ты разыграл" not in expl.short_description.lower()
    assert "поставил" not in expl.short_description.lower()
    assert "Hog Rider" in expl.short_description


def test_card_play_confirmed_kind_may_say_play() -> None:
    moment = _moment(event_type=OBS_CARD_VISIBLE, ts=31.5, card="Hog Rider")
    confirmed = [
        _Ev(
            event_type=EVENT_CARD_PLAY_CONFIRMED,
            timestamp_seconds=31.8,
            details={"card_name": "Hog Rider"},
        )
    ]
    kind = classify_explanation_kind(moment, confirmed_events=confirmed)
    assert kind == EXPLANATION_CARD_PLAY_CONFIRMED
    expl = fallback_moment_explanation(moment, kind=kind)
    assert "разыграл" in expl.short_description.lower()


def test_candidate_becomes_unknown_not_confirmed() -> None:
    for et in (OBS_CARD_PLAY_CANDIDATE, OBS_TOWER_DAMAGE_CANDIDATE, OBS_UNKNOWN):
        moment = _moment(event_type=et, card=None)
        kind = classify_explanation_kind(moment)
        assert kind == EXPLANATION_UNKNOWN
        expl = fallback_moment_explanation(moment, kind=kind)
        assert "подтверждён" not in expl.short_description.lower() or "недостаточно" in expl.short_description.lower()
        assert "ты разыграл" not in expl.short_description.lower()


def test_unknown_safe_fallback() -> None:
    moment = _moment(event_type=OBS_UNKNOWN, card=None)
    expl = fallback_moment_explanation(moment)
    assert expl.explanation_kind == EXPLANATION_UNKNOWN
    assert expl.source == "fallback"
    assert "недостаточно" in expl.short_description.lower() or "отдельные" in expl.short_description.lower()


def test_hallucinated_card_rejected() -> None:
    moment = _moment(card="Hog Rider")
    reason = validate_moment_explanation(
        title="12 сек — Hog Rider",
        description="На поле виден Mega Knight рядом с Hog Rider.",
        moment=moment,
        kind=EXPLANATION_CARD_VISIBLE,
        allowed_cards={"Hog Rider"},
        allowed_timestamps={12.0},
    )
    assert reason == "hallucinated_card"


def test_invented_timestamp_rejected() -> None:
    moment = _moment(ts=12.0)
    reason = validate_moment_explanation(
        title="99 сек — Hog Rider",
        description="На 99 секунде виден Hog Rider.",
        moment=moment,
        kind=EXPLANATION_CARD_VISIBLE,
        allowed_cards={"Hog Rider"},
        allowed_timestamps={12.0},
    )
    assert reason == "invented_timestamp"


def test_card_visible_claiming_play_rejected() -> None:
    moment = _moment(card="Hog Rider")
    reason = validate_moment_explanation(
        title="12 сек — Hog Rider",
        description="Ты разыграл Hog Rider на 12 сек.",
        moment=moment,
        kind=EXPLANATION_CARD_VISIBLE,
        allowed_cards={"Hog Rider"},
        allowed_timestamps={12.0},
    )
    assert reason == "card_visible_as_play"


@pytest.mark.parametrize(
    "text,code",
    [
        ("Потратил 5 эликсир на Hog Rider.", "invented_elixir"),
        ("Hog Rider нанес 500 урона.", "invented_damage"),
        ("Ты выиграл этот бой.", "invented_winner"),
    ],
)
def test_invented_elixir_damage_winner_rejected(text: str, code: str) -> None:
    moment = _moment(card="Hog Rider")
    reason = validate_moment_explanation(
        title="12 сек — Hog Rider",
        description=text,
        moment=moment,
        kind=EXPLANATION_CARD_VISIBLE,
        allowed_cards={"Hog Rider"},
        allowed_timestamps={12.0},
    )
    assert reason == code


def test_qwen_error_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_MOMENT_RENDER_ENABLED", "1")
    renderer = ReplayMomentRenderer(timeout_seconds=5.0)

    async def boom(*_a, **_k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(renderer, "_call_qwen", boom)

    async def _run():
        return await renderer.arender_moments([_moment()], use_qwen=True)

    out = asyncio.run(_run())
    assert len(out) == 1
    assert out[0].explanation_source == "fallback"
    assert out[0].short_description


def test_qwen_timeout_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_MOMENT_RENDER_ENABLED", "1")
    renderer = ReplayMomentRenderer(timeout_seconds=0.05)

    async def timed_out(*_a, **_k):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(renderer, "_call_qwen", timed_out)

    async def _run():
        return await renderer.arender_moments([_moment()], use_qwen=True)

    out = asyncio.run(_run())
    assert out[0].explanation_source == "fallback"


def test_qwen_invalid_output_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_MOMENT_RENDER_ENABLED", "1")
    renderer = ReplayMomentRenderer(timeout_seconds=5.0)

    async def bad(*_a, **_k):
        return '{"title":"12 сек","description":"Ты разыграл Hog Rider."}'

    monkeypatch.setattr(renderer, "_call_qwen", bad)

    async def _run():
        return await renderer.arender_moments([_moment()], use_qwen=True)

    out = asyncio.run(_run())
    assert out[0].explanation_source == "fallback"
    assert "ты разыграл" not in (out[0].short_description or "").lower()


def test_empty_visual_moments_summary_ok() -> None:
    async def _run():
        return await ReplaySummaryRenderer().arender(
            moments=[],
            limitations=["elixir_values_not_extracted"],
            use_qwen=False,
        )

    summary = asyncio.run(_run())
    assert summary.overview
    assert summary.limitations
    assert summary.source == "fallback"


def test_limitations_in_summary_fallback() -> None:
    summary = fallback_replay_summary(
        moments=[],
        limitations=["elixir_values_not_extracted", "damage_events_not_detected"],
    )
    assert "эликсир" in summary.limitations.lower()
    assert "Ограничения анализа" in summary.limitations or "не извлечены" in summary.limitations


def test_api_public_dict_strips_paths() -> None:
    moment = ReplayVisualMoment(
        event_type=OBS_CARD_VISIBLE,
        timestamp_seconds=12.0,
        confidence=0.94,
        card_name="Hog Rider",
        evidence_frame=EvidenceFrame(3, 12.0, path="/secret/frame.jpg", width=720, height=1280),
        evidence_id="tok",
        clip_path="/secret/clip.webp",
        title="12 сек — Hog Rider",
        short_description="На поле подтверждён Hog Rider.",
        explanation_kind=EXPLANATION_CARD_VISIBLE,
        explanation_source="fallback",
    )
    public = _public_visual_moment(moment.to_dict() | {"clip_path": "/secret/clip.webp"})
    blob = str(public)
    assert "/secret" not in blob
    assert "path" not in public["evidence_frame"]
    assert "clip_path" not in public
    assert public["title"] == "12 сек — Hog Rider"
    assert public["short_description"]
    assert public["explanation_kind"] == EXPLANATION_CARD_VISIBLE


def test_use_qwen_false_skips_model(monkeypatch: pytest.MonkeyPatch) -> None:
    renderer = ReplayMomentRenderer()
    calls = {"n": 0}

    async def track(*_a, **_k):
        calls["n"] += 1
        return "{}"

    monkeypatch.setattr(renderer, "_call_qwen", track)

    async def _run():
        return await renderer.arender_moments([_moment()], use_qwen=False)

    out = asyncio.run(_run())
    assert calls["n"] == 0
    assert out[0].explanation_source == "fallback"


def test_arender_moments_closes_owned_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_MOMENT_RENDER_ENABLED", "1")
    closed = {"n": 0}

    class TrackingProvider:
        async def close(self) -> None:
            closed["n"] += 1

    renderer = ReplayMomentRenderer(provider=TrackingProvider())
    renderer._owns_provider = True

    async def noop(*_a, **_k):
        return '{"title":"t","description":"d"}'

    monkeypatch.setattr(renderer, "_call_qwen", noop)

    async def _run():
        await renderer.arender_moments([_moment()], use_qwen=True)

    asyncio.run(_run())
    assert closed["n"] == 1


def test_summary_arender_closes_owned_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_MOMENT_RENDER_ENABLED", "1")
    closed = {"n": 0}

    class TrackingProvider:
        async def close(self) -> None:
            closed["n"] += 1

    renderer = ReplaySummaryRenderer(provider=TrackingProvider())
    renderer._owns_provider = True

    async def noop(*_a, **_k):
        return '{"overview":"o","limitations":"l"}'

    monkeypatch.setattr(renderer, "_call_qwen", noop)

    async def _run():
        await renderer.arender(moments=[_moment()], facts=["f"], limitations=["lim"])

    asyncio.run(_run())
    assert closed["n"] == 1