"""Stage 6: grounded tactical analysis. No invented coaching, no LLM truth."""

from __future__ import annotations

from pathlib import Path

from bot.services.ghosteek_ai.replay.battle_timeline import ReplayBattleTimelineBuilder
from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog, CatalogCard
from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact
from bot.services.ghosteek_ai.replay.events import (
    EVENT_BATTLE_STARTED,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_VISIBLE,
    EventEvidence,
    PLAYER_OPPONENT,
    PLAYER_SELF,
    PLAYER_UNKNOWN,
    ReplayEvent,
)
from bot.services.ghosteek_ai.replay.tactical_analysis import (
    ReplayTacticalAnalyzer,
    _INSUFFICIENT_MOMENT,
)

HOG = "26000000"
WITCH = "26000007"
CANNON = "27000001"


def _catalog() -> CardCatalog:
    return CardCatalog(
        (
            CatalogCard(card_id=HOG, card_name="Hog Rider"),
            CatalogCard(card_id=WITCH, card_name="Witch"),
            CatalogCard(card_id=CANNON, card_name="Cannon"),
        )
    )


def _ev(
    ts: float,
    event_type: str,
    *,
    conf: float = 0.95,
    card_id: str | None = None,
    player: str = PLAYER_UNKNOWN,
    frame: int = 0,
) -> ReplayEvent:
    return ReplayEvent(
        timestamp_seconds=ts,
        event_type=event_type,
        player=player,
        card_id=card_id,
        confidence=conf,
        source="heuristic",
        evidence=EventEvidence(
            frame_indices=(frame,),
            observation_ids=(f"t:{frame}:{event_type}",),
            timestamps=(ts,),
        ),
    )


def _forbidden(blob: str) -> None:
    low = blob.lower()
    for token in (
        "плохо потратил эликсир",
        "слишком рано поставил",
        "проиграл из-за плохой защиты",
        "elixir spent",
        "tower took",
        "bad defense",
        "you should have",
    ):
        assert token not in low


def test_insufficient_data_no_invented_coaching() -> None:
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=60.0,
        events=[],
        confirmed_events=[],
        confidence=0.4,
    )
    analysis = ReplayTacticalAnalyzer(catalog=_catalog()).analyze(
        battle_timeline=battle,
        confirmed_cards=[],
        confirmed_events=[],
        events=[],
    )
    blob = " ".join(
        [
            analysis.summary,
            *analysis.possible_mistakes,
            *analysis.recommendations,
            *analysis.positive_actions,
        ]
    )
    _forbidden(blob)
    assert _INSUFFICIENT_MOMENT in analysis.possible_mistakes
    assert "exact elixir" in analysis.limitations.what_we_dont_know
    assert "exact damage" in analysis.limitations.what_we_dont_know


def test_confirmed_card_valid_card_analysis() -> None:
    cards = [ConfirmedCardFact(HOG, "Hog Rider", 0.94, 10.0, 12.0)]
    events = [
        _ev(1.0, EVENT_BATTLE_STARTED),
        _ev(10.0, EVENT_CARD_VISIBLE, card_id=HOG, player=PLAYER_SELF),
    ]
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=90.0,
        events=events,
        confirmed_events=events,
        confirmed_cards=cards,
        confidence=0.92,
    )
    analysis = ReplayTacticalAnalyzer(catalog=_catalog()).analyze(
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=events,
        events=events,
    )
    assert any("Hog Rider" in line for line in analysis.deck_observations)
    assert any("elixir" in line.lower() for line in analysis.deck_observations)
    _forbidden(" ".join(analysis.possible_mistakes))


def test_unknown_card_ignored() -> None:
    cards = [ConfirmedCardFact("99999999", "Fake Unit", 0.99, 1.0, 1.0)]
    events = [_ev(1.0, EVENT_CARD_VISIBLE, card_id="99999999", player=PLAYER_SELF)]
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=30.0,
        events=events,
        confirmed_events=events,
        confirmed_cards=cards,
    )
    analysis = ReplayTacticalAnalyzer(catalog=_catalog()).analyze(
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=events,
    )
    blob = " ".join(analysis.deck_observations + analysis.matchup_observations)
    assert "Fake Unit" not in blob
    assert "99999999" not in " ".join(analysis.deck_observations)
    assert any(
        "could not be resolved" in x for x in analysis.limitations.what_we_dont_know
    )


def test_candidate_event_not_authoritative() -> None:
    candidates = [
        _ev(5.0, EVENT_CARD_PLAY_CANDIDATE, card_id=HOG, player=PLAYER_SELF, conf=0.88),
    ]
    confirmed = [_ev(1.0, EVENT_BATTLE_STARTED)]
    cards = [ConfirmedCardFact(HOG, "Hog Rider", 0.94, 5.0, 5.0)]
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=40.0,
        events=confirmed + candidates,
        confirmed_events=confirmed,
        confirmed_cards=cards,
    )
    analysis = ReplayTacticalAnalyzer(catalog=_catalog()).analyze(
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=confirmed,
        events=confirmed + candidates,
    )
    blob = " ".join(analysis.possible_mistakes + analysis.recommendations).lower()
    assert "candidate" in blob
    assert "рано поставил" not in blob
    assert "card_play_candidate events are not confirmed plays" in (
        analysis.limitations.what_we_dont_know
    )


def test_matchup_only_when_both_sides_confirmed() -> None:
    analyzer = ReplayTacticalAnalyzer(catalog=_catalog())
    one_side = [
        _ev(1.0, EVENT_CARD_VISIBLE, card_id=HOG, player=PLAYER_SELF),
    ]
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=50.0,
        events=one_side,
        confirmed_events=one_side,
        confirmed_cards=[ConfirmedCardFact(HOG, "Hog Rider", 0.95, 1.0, 1.0)],
    )
    a1 = analyzer.analyze(
        battle_timeline=battle,
        confirmed_cards=[ConfirmedCardFact(HOG, "Hog Rider", 0.95, 1.0, 1.0)],
        confirmed_events=one_side,
    )
    assert a1.matchup_observations == []

    both = [
        _ev(1.0, EVENT_CARD_VISIBLE, card_id=CANNON, player=PLAYER_SELF),
        _ev(2.0, EVENT_CARD_VISIBLE, card_id=HOG, player=PLAYER_OPPONENT),
    ]
    cards = [
        ConfirmedCardFact(CANNON, "Cannon", 0.95, 1.0, 1.0),
        ConfirmedCardFact(HOG, "Hog Rider", 0.95, 2.0, 2.0),
    ]
    battle2 = ReplayBattleTimelineBuilder().build(
        duration_seconds=50.0,
        events=both,
        confirmed_events=both,
        confirmed_cards=cards,
    )
    a2 = analyzer.analyze(
        battle_timeline=battle2,
        confirmed_cards=cards,
        confirmed_events=both,
    )
    # Cannon vs Hog often has counter relation in database
    assert isinstance(a2.matchup_observations, list)
    # Must not reconstruct full decks
    assert any("не восстановлены" in r.lower() or "не реконструирую" in r.lower() for r in a2.recommendations)


def test_no_full_deck_invention() -> None:
    events = [
        _ev(1.0, EVENT_CARD_VISIBLE, card_id=HOG, player=PLAYER_SELF),
        _ev(2.0, EVENT_CARD_VISIBLE, card_id=WITCH, player=PLAYER_OPPONENT),
    ]
    cards = [
        ConfirmedCardFact(HOG, "Hog Rider", 0.95, 1.0, 1.0),
        ConfirmedCardFact(WITCH, "Witch", 0.95, 2.0, 2.0),
    ]
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=80.0,
        events=events,
        confirmed_events=events,
        confirmed_cards=cards,
    )
    analysis = ReplayTacticalAnalyzer(catalog=_catalog()).analyze(
        battle_timeline=battle,
        confirmed_cards=cards,
        confirmed_events=events,
    )
    blob = " ".join(analysis.matchup_observations + analysis.deck_observations)
    assert "Matchup score (confirmed 8+8 only)" not in blob


def test_what_we_know_and_dont_know_present() -> None:
    events = [_ev(1.0, EVENT_BATTLE_STARTED)]
    battle = ReplayBattleTimelineBuilder().build(
        duration_seconds=100.0,
        events=events,
        confirmed_events=events,
    )
    analysis = ReplayTacticalAnalyzer(catalog=_catalog()).analyze(
        battle_timeline=battle,
        confirmed_events=events,
    )
    assert analysis.limitations.what_we_know
    assert "battle_started confirmed" in analysis.limitations.what_we_know
    for key in ("exact elixir", "exact damage", "tower HP", "frame-level timing"):
        assert key in analysis.limitations.what_we_dont_know


def test_null_timeline_insufficient() -> None:
    analysis = ReplayTacticalAnalyzer(catalog=_catalog()).analyze(battle_timeline=None)
    assert analysis.confidence == 0.0
    assert _INSUFFICIENT_MOMENT in analysis.possible_mistakes


def test_no_llm_in_tactical_module() -> None:
    import bot.services.ghosteek_ai.replay.tactical_analysis as mod

    src = Path(mod.__file__).read_text(encoding="utf-8").lower()
    assert "qwen" not in src
    assert "ollama" not in src
