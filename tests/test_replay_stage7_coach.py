"""Stage 7: Qwen replay coach renderer. Structured facts only — no video SoT."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.services.ghosteek_ai.replay.battle_timeline import ReplayBattleTimelineBuilder
from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact
from bot.services.ghosteek_ai.replay.coach_renderer import (
    REPLAY_COACH_SYSTEM_PROMPT,
    REPLAY_RENDERER_SYSTEM_PROMPT,
    ReplayCoachPromptBuilder,
    ReplayCoachRenderer,
    apply_replay_coach_gate,
    build_replay_coach_envelope,
    format_facts_block,
    render_replay_coach_fallback,
    replay_coach_generate_kwargs,
    validate_replay_coach_response,
)
from bot.services.ghosteek_ai.replay.events import (
    EVENT_BATTLE_STARTED,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_VISIBLE,
    EventEvidence,
    PLAYER_SELF,
    ReplayEvent,
)
from bot.services.ghosteek_ai.replay.tactical_analysis import (
    AnalysisLimitations,
    ReplayTacticalAnalysis,
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


def _sample_bundle():
    cards = [ConfirmedCardFact("26000000", "Hog Rider", 0.94, 31.8, 33.0)]
    confirmed = [
        _ev(1.0, EVENT_BATTLE_STARTED),
        _ev(31.8, EVENT_CARD_VISIBLE, card_id="26000000"),
    ]
    events = confirmed + [
        _ev(32.5, EVENT_CARD_PLAY_CANDIDATE, card_id="26000000", conf=0.88),
    ]
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=90.0,
        events=events,
        confirmed_events=confirmed,
        confirmed_cards=cards,
        confidence=0.91,
    )
    tactical = ReplayTacticalAnalysis(
        summary="Уверенно вижу на записи 1 карт(ы). Собрал 2 подтверждённых момента(ов) по бою.",
        positive_actions=["Подтверждено начало боя."],
        possible_mistakes=["По доступным данным я не могу подтвердить причину этого момента."],
        matchup_observations=[],
        deck_observations=["Hog Rider: elixir 4; type troop"],
        recommendations=["Полные колоды пока не собрал — недостающие карты не угадываю."],
        confidence=0.72,
        limitations=AnalysisLimitations(
            what_we_know=["battle_start confirmed"],
            what_we_dont_know=["exact elixir", "exact damage", "tower HP"],
        ),
    )
    return cards, confirmed, events, battle, tactical


def test_envelope_has_no_raw_video() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()
    env = build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=events,
    )
    blob = str(env).lower()
    assert env["data"]["has_video_payload"] is False
    assert env["data"]["has_raw_frames"] is False
    assert "ffmpeg" not in blob
    assert ".mp4" not in blob
    assert "base64" not in blob
    assert "raw frames" not in format_facts_block(env).lower()


def test_facts_preserved_in_envelope() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()
    env = build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=events,
    )
    facts = " ".join(env["data"]["facts"])
    assert "Hog Rider" in facts
    assert (
        "battle_start" in facts
        or "battle_started" in facts
        or "EVENT_BATTLE" in facts
        or "type=battle_start" in facts
    )
    assert "exact elixir" in facts
    assert 31.8 in env["data"]["allowed_timestamps"]


def test_card_names_only_from_confirmed() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()
    env = build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=events,
    )
    assert "Hog Rider" in env["data"]["allowed_card_ids"]
    assert "Wizard" not in env["data"]["allowed_card_ids"]
    ok, reason = validate_replay_coach_response(
        "Бери Wizard и дави башню.",
        env,
    )
    assert ok is False
    assert "unknown_card" in reason


def test_timestamps_only_from_confirmed_events() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()
    env = build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=events,
    )
    ok, reason = validate_replay_coach_response(
        "На 77-й секунде ты сыграл Hog Rider.",
        env,
    )
    assert ok is False
    assert "unknown_timestamp" in reason
    ok2, _ = validate_replay_coach_response(
        "На 32-й секунде видно Hog Rider.",
        env,
    )
    assert ok2 is True


def test_candidate_events_marked_uncertain() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()
    env = build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=events,
    )
    notes = " ".join(env["data"]["candidate_notes"] + env["data"]["facts"])
    assert "candidate" in notes.lower()
    assert "похоже" in notes.lower() or "возможно" in notes.lower() or "not confirmed" in notes.lower()


def test_insufficient_data_handled_honestly() -> None:
    battle = ReplayBattleTimelineBuilder().build(duration_seconds=40.0, events=[], confirmed_events=[])
    tactical = ReplayTacticalAnalysis(
        summary="мало данных",
        possible_mistakes=["По доступным данным я не могу подтвердить причину этого момента."],
        limitations=AnalysisLimitations(what_we_dont_know=["exact elixir"]),
    )
    env = build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=[],
        confirmed_events=[],
    )
    text = render_replay_coach_fallback(env)
    assert "подтвердить" in text.lower() or "мало" in text.lower() or "не могу" in text.lower()
    assert "wizard" not in text.lower()


def test_qwen_failure_uses_template() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()

    class Boom:
        async def generate(self, *args, **kwargs):
            raise TimeoutError("ollama down")

    renderer = ReplayCoachRenderer(provider=Boom())

    async def _run():
        return await renderer.arender(
            tactical=tactical,
            battle_timeline=battle,
            confirmed_cards=cards,
            confirmed_events=confirmed,
            events=events,
        )

    result = asyncio.run(_run())
    assert result.source == "template"
    assert result.text.strip()
    assert "Hog Rider" in result.text or "подтвержд" in result.text.lower()


def test_invalid_qwen_response_gated_to_template() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()
    env = build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=events,
    )
    gated = apply_replay_coach_gate(
        "Ты плохо потратил эликсир и проиграл из-за плохой защиты. Бери Mega Knight.",
        env,
    )
    assert "плохо потратил эликсир" not in gated.lower()
    assert "mega knight" not in gated.lower()


def test_alive_template_reply_is_coach_like() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()
    result = ReplayCoachRenderer().render_template(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=events,
    )
    assert len(result.text) > 40
    assert result.source == "template"
    # Not a raw JSON dump
    assert "allowed_card_ids" not in result.text
    assert "what_we_dont_know" not in result.text


def test_prompt_contains_system_and_no_video_bytes() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()
    env = build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=events,
    )
    messages = ReplayCoachPromptBuilder(env).build(SimpleNamespace(raw_message="Разбери реплей"))
    joined = "\n".join(m.content for m in messages)
    assert "Ghosteek AI" in REPLAY_RENDERER_SYSTEM_PROMPT
    assert "не являешься источником фактов" in REPLAY_RENDERER_SYSTEM_PROMPT.lower()
    assert REPLAY_COACH_SYSTEM_PROMPT == REPLAY_RENDERER_SYSTEM_PROMPT
    assert "FACTS:" in joined
    assert "ReplayFacts" in joined
    assert b"\x00\x00\x00\x18ftyp" not in joined.encode("utf-8", errors="ignore")


def test_generate_kwargs_compact() -> None:
    kw = replay_coach_generate_kwargs()
    assert kw["think"] is False
    assert 256 <= int(kw["max_tokens"]) <= 384
    assert 0.3 <= float(kw["temperature"]) <= 0.45


def test_mocked_qwen_success_path() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()

    class OkProvider:
        async def generate(self, messages, tools=None, **kwargs):
            del tools
            assert kwargs.get("think") is False
            joined = " ".join(getattr(m, "content", str(m)) for m in messages)
            assert "FACTS:" in joined
            assert "ftyp" not in joined
            return SimpleNamespace(
                message={"role": "assistant", "content": "По подтверждённым данным вижу Hog Rider. Этот момент с plays я пока не могу подтвердить по видео."},
                raw={},
            )

    # OllamaResponseGenerator expects provider.generate returning LLMGenerateResult-like
    # Use arender's internal path via monkeypatch of _call_qwen
    renderer = ReplayCoachRenderer()

    async def _fake_call(envelope, *, user_message=None):
        del user_message
        return "По подтверждённым данным вижу Hog Rider. Этот момент я пока не могу подтвердить по видео."

    renderer._call_qwen = _fake_call  # type: ignore[method-assign]

    async def _run():
        return await renderer.arender(
            tactical=tactical,
            battle_timeline=battle,
            confirmed_cards=cards,
            confirmed_events=confirmed,
            events=events,
        )

    result = asyncio.run(_run())
    assert result.source == "qwen"
    assert "Hog Rider" in result.text


def test_no_llm_truth_in_module_doc() -> None:
    import bot.services.ghosteek_ai.replay.coach_renderer as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "NOT source of truth" in src or "не является" in src.lower() or "NOT source" in src
    assert "raw video" in src.lower() or "No raw video" in src


def test_followup_returns_coach_when_present() -> None:
    from bot.services.ghosteek_ai.replay_followup import reply_replay_pending_analysis

    text = reply_replay_pending_analysis(
        {
            "status": "cr_replay",
            "filename": "a.mp4",
            "duration_seconds": 90,
            "width": 720,
            "height": 1280,
            "confidence": 0.9,
            "coach_reply": "Живой тренерский разбор: вижу Hog Rider.",
            "coach_source": "template",
        }
    )
    assert text == "Живой тренерский разбор: вижу Hog Rider."


def test_arender_closes_owned_provider() -> None:
    cards, confirmed, events, battle, tactical = _sample_bundle()
    closed = {"n": 0}

    class TrackingProvider:
        async def close(self) -> None:
            closed["n"] += 1

    renderer = ReplayCoachRenderer(provider=TrackingProvider())
    renderer._owns_provider = True

    async def _fake_call(envelope, *, user_message=None):
        del envelope, user_message
        return "По подтверждённым данным вижу Hog Rider."

    renderer._call_qwen = _fake_call  # type: ignore[method-assign]

    async def _run():
        return await renderer.arender(
            tactical=tactical,
            battle_timeline=battle,
            confirmed_cards=cards,
            confirmed_events=confirmed,
            events=events,
        )

    asyncio.run(_run())
    assert closed["n"] == 1
