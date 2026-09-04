"""Only real, canonical cards may appear in the mastery list."""

from __future__ import annotations

import pytest

from bot.services import player_collection


@pytest.mark.parametrize(
    "badge_name",
    [
        "MasteryEliteArcher",
        "MasterySnowball",
        "MasteryAngryBarbarians",
        "MasteryDarkWitch",
        "MasteryMiniSparkys",
        "MasterySkeletonBalloon",
        "MasteryWitchMother",
    ],
)
def test_non_card_mastery_badges_are_ignored(
    monkeypatch: pytest.MonkeyPatch, badge_name: str
) -> None:
    monkeypatch.setattr(player_collection, "resolve_card_name", lambda _: "Archers")

    assert player_collection._mastery_card_name(badge_name) is None


def test_unknown_mastery_badge_does_not_create_a_fake_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(player_collection, "resolve_card_name", lambda _: None)

    assert player_collection._mastery_card_name("MasteryImaginaryCard") is None


def test_known_internal_mastery_badge_still_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        player_collection,
        "resolve_card_name",
        lambda raw: "Archers" if raw == "Archer" else None,
    )

    assert player_collection._mastery_card_name("MasteryArcher") == "Archers"


def test_mastery_catalog_has_exactly_current_card_count() -> None:
    from bot.services.card_knowledge import canonical_card_names

    assert len(canonical_card_names()) == 122
