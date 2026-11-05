"""Meta-backed upgrade priorities must remain grounded in their inputs."""

from __future__ import annotations

from bot.api.schemas import MetaUpgradeRecommendationsResponse
from bot.services.meta_upgrade_recommendations import build_meta_upgrade_recommendations


NAMES = [
    "Knight",
    "Archers",
    "Goblins",
    "Fireball",
    "Giant",
    "Musketeer",
    "Mini P.E.K.K.A",
    "Zap",
]


def _collection(level: int = 7) -> dict:
    return {
        "current_deck": list(NAMES),
        "cards": [
            {
                "name": name,
                "name_ru": name,
                "icon": "",
                "icon_base": "",
                "owned": True,
                "level": level,
                "max_level": 16,
            }
            for name in NAMES
        ],
    }


def _meta(status: str = "ok") -> dict:
    return {
        "status": status,
        "updated_at": "2026-09-10T10:00:00+00:00",
        "sample_note": "Test sample",
        "decks": [
            {
                "cards": [{"name": name} for name in NAMES],
                "games_count": 120,
                "wins": 72,
            }
        ],
    }


def _player(*, has_collection: bool = True) -> dict:
    return {
        "trophies": 2_000,
        "arena": {"id": 54_000_007, "name": "Royal Arena"},
        "cards": [{"name": name} for name in NAMES] if has_collection else [],
    }


def test_priorities_use_active_deck_meta_and_arena_target() -> None:
    result = build_meta_upgrade_recommendations(
        _collection(),
        _player(),
        _meta(),
    )

    assert result["status"] == "ok"
    assert result["arena"] == 7
    assert result["recommended_level"] == 8
    assert len(result["cards"]) == 5
    assert result["recommended_level"] == 8
    assert len(result["current_deck_cards"]) == 8
    assert all(card["level"] == 7 for card in result["current_deck_cards"])
    assert all(card["name"] in NAMES for card in result["cards"])
    assert all(card["recommended_level"] == 8 and card["deficit"] == 1 for card in result["cards"])


def test_priorities_fail_closed_without_reliable_meta() -> None:
    result = build_meta_upgrade_recommendations(
        _collection(),
        _player(),
        _meta("stale"),
    )

    assert result["status"] == "meta_unavailable"
    assert result["cards"] == []
    assert result["recommended_level"] is None
    assert [card["level"] for card in result["current_deck_cards"]] == [7] * 8


def test_priorities_report_missing_current_deck() -> None:
    result = build_meta_upgrade_recommendations(
        {"current_deck": [], "cards": []}, _player(), _meta(),
    )

    assert result["status"] == "no_current_deck"
    assert result["current_deck_cards"] == []
    assert result["cards"] == []


def test_priorities_show_deck_names_without_claiming_missing_levels() -> None:
    result = build_meta_upgrade_recommendations(
        _collection(), _player(has_collection=False), _meta(),
    )

    assert result["status"] == "no_collection"
    assert len(result["current_deck_cards"]) == 8
    assert all(card["level"] is None for card in result["current_deck_cards"])
    assert result["recommended_level"] is None
    assert result["cards"] == []


def test_priorities_report_no_meta_matches_but_keep_verified_deck_levels() -> None:
    meta = _meta()
    meta["decks"] = [{
        "cards": [{"name": "P.E.K.K.A"}],
        "games_count": 50,
        "wins": 25,
    }]
    result = build_meta_upgrade_recommendations(_collection(), _player(), meta)

    assert result["status"] == "no_meta_matches"
    assert result["cards"] == []
    assert result["recommended_level"] is None
    assert [card["level"] for card in result["current_deck_cards"]] == [7] * 8


def test_all_response_states_match_api_contract() -> None:
    cases = [
        build_meta_upgrade_recommendations(_collection(), _player(), _meta()),
        build_meta_upgrade_recommendations(_collection(), _player(), _meta("stale")),
        build_meta_upgrade_recommendations({"current_deck": [], "cards": []}, _player(), _meta()),
        build_meta_upgrade_recommendations(_collection(), _player(has_collection=False), _meta()),
    ]

    for payload in cases:
        response = MetaUpgradeRecommendationsResponse(**payload)
        serialized = response.model_dump()
        assert "current_deck_cards" in serialized
        assert "cards" in serialized
        assert serialized["status"] == payload["status"]
