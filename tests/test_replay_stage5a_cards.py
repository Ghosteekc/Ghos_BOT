"""Stage 5A: catalog-backed card recognition. No Qwen, no invented plays."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog, CatalogCard
from bot.services.ghosteek_ai.replay.card_recognizer import (
    CONF_HIGH,
    CONF_MEDIUM,
    LOC_OPPONENT_HAND,
    LOC_PLAYER_HAND,
    LOC_UNKNOWN,
    AmbiguousCardObservation,
    ConfirmedCardObservation,
    HeuristicCardRecognizer,
    RawCardProbeHit,
    VisionCardRecognizer,
    classify_probe_hits,
    group_confirmed_cards,
)
from bot.services.ghosteek_ai.replay.facts import ReplayFactsBuilder
from bot.services.ghosteek_ai.replay.models import (
    DEFAULT_LIMITATIONS,
    OBS_GAMEPLAY_SCREEN,
    ReplayDetection,
    TimelineObservation,
)

HOG_ID = "26000000"
WITCH_ID = "26000007"


def _catalog() -> CardCatalog:
    return CardCatalog(
        (
            CatalogCard(card_id=HOG_ID, card_name="Hog Rider"),
            CatalogCard(card_id=WITCH_ID, card_name="Witch"),
            CatalogCard(card_id="28000000", card_name="Fireball"),
        )
    )


def _obs(
    card_id: str,
    name: str,
    conf: float,
    frame: int,
    ts: float,
    *,
    location: str = LOC_UNKNOWN,
) -> ConfirmedCardObservation:
    return ConfirmedCardObservation(
        card_id=card_id,
        card_name=name,
        confidence=conf,
        frame_index=frame,
        timestamp_seconds=ts,
        location=location,
    )


def test_known_card_accepted() -> None:
    confirmed, ambiguous = classify_probe_hits(
        [RawCardProbeHit(card_id=HOG_ID, card_name="Hog Rider", confidence=0.94)],
        catalog=_catalog(),
        frame_index=3,
        timestamp_seconds=31.8,
    )
    assert ambiguous == []
    assert len(confirmed) == 1
    assert confirmed[0].card_id == HOG_ID
    assert confirmed[0].card_name == "Hog Rider"
    assert confirmed[0].confidence >= CONF_HIGH


def test_unknown_card_rejected() -> None:
    confirmed, ambiguous = classify_probe_hits(
        [RawCardProbeHit(card_id="99999999", card_name="Fake Dragon", confidence=0.99)],
        catalog=_catalog(),
        frame_index=0,
        timestamp_seconds=1.0,
    )
    assert confirmed == []
    assert ambiguous == []


def test_low_confidence_rejected() -> None:
    confirmed, ambiguous = classify_probe_hits(
        [RawCardProbeHit(card_id=HOG_ID, card_name="Hog Rider", confidence=0.60)],
        catalog=_catalog(),
        frame_index=0,
        timestamp_seconds=1.0,
    )
    assert confirmed == []
    assert ambiguous == []
    assert 0.60 < CONF_MEDIUM


def test_medium_confidence_not_authoritative_fact() -> None:
    confirmed, ambiguous = classify_probe_hits(
        [RawCardProbeHit(card_id=HOG_ID, card_name="Hog Rider", confidence=0.82)],
        catalog=_catalog(),
        frame_index=0,
        timestamp_seconds=1.0,
    )
    assert confirmed == []
    assert ambiguous == []
    assert CONF_MEDIUM <= 0.82 < CONF_HIGH

    facts = ReplayFactsBuilder().build(
        ReplayDetection(status="cr_replay", confidence=0.9, frames_analyzed=1),
        [TimelineObservation(1.0, 0, OBS_GAMEPLAY_SCREEN, 0.8)],
        duration_seconds=10.0,
        confirmed_cards=group_confirmed_cards([]),
    )
    assert facts is not None
    assert facts.confirmed_cards == []


def test_ambiguous_cards_not_converted_to_fact() -> None:
    confirmed, ambiguous = classify_probe_hits(
        [
            RawCardProbeHit(card_id=HOG_ID, card_name="Hog Rider", confidence=0.81),
            RawCardProbeHit(card_id=WITCH_ID, card_name="Witch", confidence=0.78),
        ],
        catalog=_catalog(),
        frame_index=2,
        timestamp_seconds=12.0,
    )
    assert confirmed == []
    assert len(ambiguous) == 1
    assert isinstance(ambiguous[0], AmbiguousCardObservation)
    assert len(ambiguous[0].candidates) >= 2

    result = ReplayFactsBuilder().build(
        ReplayDetection(status="cr_replay", confidence=0.9, frames_analyzed=1),
        [],
        duration_seconds=20.0,
        confirmed_cards=[],
        ambiguous_cards=ambiguous,
    )
    assert result is not None
    assert result.confirmed_cards == []
    assert len(result.ambiguous_cards) == 1


def test_card_database_is_source_of_truth() -> None:
    catalog = _catalog()
    names = {c.card_name for c in catalog.all_cards()}
    assert "Hog Rider" in names
    assert "Invented Mega Unit" not in names

    # Name alone must resolve only if in catalog
    hit = RawCardProbeHit(card_id=None, card_name="Hog Rider", confidence=0.95)
    confirmed, _ = classify_probe_hits(
        [hit], catalog=catalog, frame_index=0, timestamp_seconds=0.0
    )
    assert confirmed[0].card_id == HOG_ID

    fake = RawCardProbeHit(card_id=None, card_name="Invented Mega Unit", confidence=0.99)
    confirmed2, _ = classify_probe_hits(
        [fake], catalog=catalog, frame_index=0, timestamp_seconds=0.0
    )
    assert confirmed2 == []


def test_duplicate_frames_grouped() -> None:
    observations = [
        _obs(HOG_ID, "Hog Rider", 0.94, 0, 32.1),
        _obs(HOG_ID, "Hog Rider", 0.92, 1, 32.4),
        _obs(HOG_ID, "Hog Rider", 0.96, 2, 32.7),
        _obs(HOG_ID, "Hog Rider", 0.91, 3, 33.0),
    ]
    grouped = group_confirmed_cards(observations)
    assert len(grouped) == 1
    assert grouped[0].first_seen == pytest.approx(32.1)
    assert grouped[0].last_seen == pytest.approx(33.0)
    assert grouped[0].confidence == pytest.approx(0.96)


def test_timestamps_preserved() -> None:
    observations = [
        _obs(HOG_ID, "Hog Rider", 0.94, 0, 31.8),
        _obs(HOG_ID, "Hog Rider", 0.93, 1, 33.0),
        _obs(WITCH_ID, "Witch", 0.91, 2, 40.0),
    ]
    grouped = group_confirmed_cards(observations)
    by_id = {g.card_id: g for g in grouped}
    assert by_id[HOG_ID].first_seen == pytest.approx(31.8)
    assert by_id[HOG_ID].last_seen == pytest.approx(33.0)
    assert by_id[WITCH_ID].first_seen == pytest.approx(40.0)


def test_player_opponent_location_uncertainty_handled() -> None:
    confirmed, _ = classify_probe_hits(
        [
            RawCardProbeHit(
                card_id=HOG_ID,
                card_name="Hog Rider",
                confidence=0.95,
                location="maybe_hand",
            )
        ],
        catalog=_catalog(),
        frame_index=0,
        timestamp_seconds=1.0,
    )
    assert confirmed[0].location == LOC_UNKNOWN

    confirmed2, _ = classify_probe_hits(
        [
            RawCardProbeHit(
                card_id=HOG_ID,
                card_name="Hog Rider",
                confidence=0.95,
                location=LOC_PLAYER_HAND,
            )
        ],
        catalog=_catalog(),
        frame_index=0,
        timestamp_seconds=1.0,
    )
    assert confirmed2[0].location == LOC_PLAYER_HAND

    confirmed3, _ = classify_probe_hits(
        [
            RawCardProbeHit(
                card_id=WITCH_ID,
                card_name="Witch",
                confidence=0.95,
                location=LOC_OPPONENT_HAND,
            )
        ],
        catalog=_catalog(),
        frame_index=1,
        timestamp_seconds=2.0,
    )
    assert confirmed3[0].location == LOC_OPPONENT_HAND


def test_no_invented_card_names() -> None:
    recognizer = HeuristicCardRecognizer(catalog=_catalog(), probe=None)
    confirmed, ambiguous = recognizer.recognize_frame(
        "missing.jpg", frame_index=0, timestamp_seconds=0.0
    )
    assert confirmed == []
    assert ambiguous == []

    class _Probe:
        def probe(self, frame_path, *, frame_index, timestamp_seconds):
            del frame_path, frame_index, timestamp_seconds
            return [
                RawCardProbeHit(card_id="x", card_name="Not A Real Card", confidence=0.99),
            ]

    recognizer2 = HeuristicCardRecognizer(catalog=_catalog(), probe=_Probe())
    confirmed2, _ = recognizer2.recognize_frame("f.jpg", frame_index=0, timestamp_seconds=0.0)
    assert confirmed2 == []


def test_no_card_play_generated() -> None:
    grouped = group_confirmed_cards(
        [_obs(HOG_ID, "Hog Rider", 0.94, 0, 31.8, location="played_card_area")]
    )
    result = ReplayFactsBuilder().build(
        ReplayDetection(status="cr_replay", confidence=0.95, frames_analyzed=4),
        [TimelineObservation(31.8, 0, OBS_GAMEPLAY_SCREEN, 0.8)],
        duration_seconds=60.0,
        confirmed_cards=grouped,
    )
    assert result is not None
    assert "card_play_events_not_confirmed" in result.limitations
    assert "card_play_events_not_detected" in result.limitations
    assert set(DEFAULT_LIMITATIONS).issubset(set(result.limitations))
    blob = " ".join(result.facts).lower()
    assert "played" not in blob
    assert "damage" not in blob
    assert "elixir spent" not in blob
    # Presence fact only — no play event fields
    assert len(result.confirmed_cards) == 1
    card = result.confirmed_cards[0].to_dict()
    assert set(card.keys()) == {
        "card_id",
        "card_name",
        "confidence",
        "first_seen",
        "last_seen",
    }
    assert "card_play" not in card
    assert "deployed" not in card


def test_confirmed_cards_high_only_in_facts() -> None:
    from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact

    high = group_confirmed_cards([_obs(HOG_ID, "Hog Rider", 0.94, 0, 31.8)])
    lowish = [
        ConfirmedCardFact(
            card_id=WITCH_ID,
            card_name="Witch",
            confidence=0.88,
            first_seen=1.0,
            last_seen=1.2,
        )
    ]
    result = ReplayFactsBuilder().build(
        ReplayDetection(status="cr_replay", confidence=0.9, frames_analyzed=2),
        [],
        duration_seconds=10.0,
        confirmed_cards=list(high) + lowish,
    )
    assert result is not None
    assert len(result.confirmed_cards) == 1
    assert result.confirmed_cards[0].card_id == HOG_ID
    example = result.confirmed_cards[0].to_dict()
    assert example["card_name"] == "Hog Rider"
    assert example["confidence"] >= 0.90
    assert example["first_seen"] == pytest.approx(31.8)


def test_heuristic_without_probe_returns_empty() -> None:
    recognizer = HeuristicCardRecognizer(catalog=_catalog())
    confirmed, ambiguous = recognizer.recognize_frame(
        "frame.jpg", frame_index=1, timestamp_seconds=5.0
    )
    assert confirmed == []
    assert ambiguous == []


def test_vision_recognizer_stub_safe() -> None:
    vision = VisionCardRecognizer(catalog=_catalog())
    confirmed, ambiguous = vision.recognize_frame(
        "frame.jpg", frame_index=0, timestamp_seconds=0.0
    )
    assert confirmed == []
    assert ambiguous == []


def test_qwen_not_used_in_card_modules() -> None:
    import bot.services.ghosteek_ai.replay.card_catalog as catalog_mod
    import bot.services.ghosteek_ai.replay.card_recognizer as recog_mod

    for mod in (catalog_mod, recog_mod):
        src = Path(mod.__file__).read_text(encoding="utf-8").lower()
        assert "qwen" not in src
        assert "ollama" not in src
