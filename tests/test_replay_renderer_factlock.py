"""Regression: Qwen replay renderer fact-lock (grounded trainer only)."""

from __future__ import annotations

from pathlib import Path

from bot.services.ghosteek_ai.replay.battle_timeline import ReplayBattleTimelineBuilder
from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact
from bot.services.ghosteek_ai.replay.coach_renderer import (
    REPLAY_RENDERER_SYSTEM_PROMPT,
    apply_replay_coach_gate,
    build_replay_coach_envelope,
    format_facts_block,
    render_replay_coach_fallback,
    validate_replay_coach_response,
)
from bot.services.ghosteek_ai.replay.events import (
    EVENT_BATTLE_START,
    EVENT_CARD_IDENTITY_VISIBLE,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_PLAY_CONFIRMED,
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


def _env(*, with_play: bool = False, with_candidate: bool = True):
    cards = [ConfirmedCardFact("26000000", "Hog Rider", 0.94, 31.8, 33.0)]
    confirmed = [
        _ev(1.0, EVENT_BATTLE_START),
        _ev(31.8, EVENT_CARD_IDENTITY_VISIBLE, card_id="26000000"),
    ]
    if with_play:
        confirmed.append(_ev(35.0, EVENT_CARD_PLAY_CONFIRMED, card_id="26000000"))
    events = list(confirmed)
    candidates = []
    if with_candidate:
        cand = _ev(32.5, EVENT_CARD_PLAY_CANDIDATE, card_id="26000000", conf=0.88)
        events.append(cand)
        candidates.append(cand)
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=90.0,
        events=events,
        confirmed_events=confirmed,
        confirmed_cards=cards,
        confidence=0.91,
    )
    tactical = ReplayTacticalAnalysis(
        summary="Уверенно вижу на записи Hog Rider.",
        positive_actions=["Подтверждено начало боя."],
        possible_mistakes=["По доступным данным я не могу подтвердить причину этого момента."],
        recommendations=["Держи темп по тому, что уже видно уверенно."],
        confidence=0.7,
        limitations=AnalysisLimitations(
            what_we_know=["battle_start confirmed"],
            what_we_dont_know=["exact elixir", "exact damage", "tower HP"],
        ),
    )
    return build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=events,
        candidate_events=candidates,
        limitations=["card_play_events_not_confirmed", "elixir_values_not_extracted"],
        facts=["Clash Royale gameplay interface detected"],
    )


def test_vision_card_mention_allowed_without_heuristic_fact() -> None:
    """Vision troop_visible must be mentionable even without HeuristicCardRecognizer hits."""
    from bot.services.ghosteek_ai.replay.events import (
        EVENT_CARD_IDENTITY_VISIBLE,
        EventEvidence,
        PLAYER_SELF,
        ReplayEvent,
    )

    vision_ev = ReplayEvent(
        timestamp_seconds=12.0,
        event_type=EVENT_CARD_IDENTITY_VISIBLE,
        player=PLAYER_SELF,
        card_id="28000000",
        confidence=0.86,
        source="vision",
        evidence=EventEvidence((0,), ("vision:0:troop_visible",), (12.0,)),
        details={"card_name": "Goblin Barrel"},
    )
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=44.5,
        events=[vision_ev],
        confirmed_events=[vision_ev],
        confirmed_cards=[],
        confidence=0.8,
    )
    env = build_replay_coach_envelope(
        tactical=None,
        battle_timeline=battle,
        confirmed_cards=[],
        confirmed_events=[vision_ev],
        events=[vision_ev],
        candidate_events=[],
        limitations=[],
        facts=["Clash Royale gameplay interface detected"],
    )
    assert "Goblin Barrel" in env["data"]["allowed_card_ids"]
    ok, reason = validate_replay_coach_response(
        "Коротко: по кадрам уверенно вижу Goblin Barrel. Что заметил: карта на арене.",
        env,
    )
    assert ok is True, reason


def test_hallucinated_card_rejected() -> None:
    env = _env()
    ok, reason = validate_replay_coach_response(
        "Бери Mega Knight и дави башню Hog Rider.",
        env,
    )
    assert ok is False
    assert "unknown_card" in reason
    gated = apply_replay_coach_gate(
        "Бери Mega Knight и дави башню.",
        env,
    )
    assert "mega knight" not in gated.lower()


def test_replay_duration_allowed_as_timestamp() -> None:
    env = _env()
    stamps = env["data"]["allowed_timestamps"]
    assert 90.0 in stamps
    ok, reason = validate_replay_coach_response(
        "Коротко: запись длится около 90 секунд, Hog Rider виден уверенно.",
        env,
    )
    assert ok is True, reason


def test_hallucinated_timestamp_rejected() -> None:
    env = _env()
    ok, reason = validate_replay_coach_response(
        "На 77-й секунде видно Hog Rider.",
        env,
    )
    assert ok is False
    assert "unknown_timestamp" in reason


def test_candidate_treated_as_confirmed_rejected() -> None:
    env = _env(with_play=False, with_candidate=True)
    assert env["data"]["confirmed_play_card_names"] == []
    ok, reason = validate_replay_coach_response(
        "Ты сыграл Hog Rider — это точно.",
        env,
    )
    assert ok is False
    assert reason == "candidate_as_confirmed"
    ok2, reason2 = validate_replay_coach_response(
        "Точно сыграл Hog Rider на этой секунде.",
        env,
    )
    assert ok2 is False
    assert reason2 == "candidate_as_confirmed"


def test_unsupported_damage_rejected() -> None:
    env = _env()
    assert env["data"]["has_damage_facts"] is False
    ok, reason = validate_replay_coach_response(
        "Башня потеряла 450 урона от Hog Rider.",
        env,
    )
    assert ok is False
    assert reason == "unsupported_damage"


def test_unsupported_winner_rejected() -> None:
    env = _env()
    assert env["data"]["has_winner_facts"] is False
    ok, reason = validate_replay_coach_response(
        "Ты выиграл этот бой за счёт Hog Rider.",
        env,
    )
    assert ok is False
    assert reason == "unsupported_winner"


def test_valid_grounded_advice_accepted() -> None:
    env = _env(with_play=False, with_candidate=True)
    text = (
        "Коротко: по подтверждённым данным вижу Hog Rider и начало боя. "
        "Что заметил: карта уверенно видна на записи. "
        "Чего не удалось подтвердить: точный розыгрыш и эликсир пока не извлекаются."
    )
    ok, reason = validate_replay_coach_response(text, env)
    assert ok is True, reason
    assert apply_replay_coach_gate(text, env) == text


def test_valid_confirmed_play_advice_accepted() -> None:
    env = _env(with_play=True, with_candidate=False)
    assert "Hog Rider" in env["data"]["confirmed_play_card_names"]
    text = (
        "Коротко: уверенно вижу Hog Rider. "
        "Что заметил: на 35-й секунде подтверждён розыгрыш Hog Rider. "
        "Что улучшить: держи темп по тому, что уже видно уверенно."
    )
    ok, reason = validate_replay_coach_response(text, env)
    assert ok is True, reason


def test_insufficient_data_response() -> None:
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=40.0, events=[], confirmed_events=[]
    )
    tactical = ReplayTacticalAnalysis(
        summary="мало данных",
        limitations=AnalysisLimitations(what_we_dont_know=["exact elixir", "exact damage"]),
    )
    env = build_replay_coach_envelope(
        tactical=tactical,
        battle_timeline=battle,
        confirmed_cards=[],
        confirmed_events=[],
        candidate_events=[],
        limitations=["card_play_events_not_confirmed"],
    )
    text = render_replay_coach_fallback(env)
    low = text.lower()
    assert "распознался" in low or "не буду придумывать" in low or "не могу" in low
    assert "wizard" not in low
    assert "mega knight" not in low
    assert "grounded replay analysis" not in low


def test_envelope_is_compact_replay_facts_only() -> None:
    env = _env()
    blob = str(env).lower()
    assert env["data"]["has_video_payload"] is False
    assert env["data"]["has_raw_frames"] is False
    assert env["data"]["has_full_timeline"] is False
    assert env["data"]["has_debug_objects"] is False
    assert ".mp4" not in blob
    assert "ffmpeg" not in blob
    assert "base64" not in blob
    block = format_facts_block(env)
    assert "ReplayFacts" in block
    assert "FACTS:" in block
    assert "Candidates are NOT facts" in block
    assert "CONFIRMED PLAYS" in block


def test_renderer_prompt_rules_present() -> None:
    low = REPLAY_RENDERER_SYSTEM_PROMPT.lower()
    assert "ghosteek ai" in low
    assert "не являешься источником фактов" in low
    assert "candidate" in low
    assert "timestamp" in low
    assert "grounded replay analysis" in low
    assert "structured facts" in low


def test_cr_fact_lock_module_untouched_by_replay_gate() -> None:
    """Replay gate must not remove/replace the shared CR validator helpers."""
    import bot.services.ghosteek_ai.safety.local_renderer_validator as cr_lock
    import bot.services.ghosteek_ai.replay.coach_renderer as replay_mod

    assert hasattr(cr_lock, "find_ungrounded_cards")
    assert hasattr(cr_lock, "validate_local_renderer_response") or hasattr(
        cr_lock, "LocalRendererValidation"
    )
    src = Path(replay_mod.__file__).read_text(encoding="utf-8")
    assert "find_ungrounded_cards" in src
    assert "Does not weaken" in src or "does not weaken" in src.lower()
