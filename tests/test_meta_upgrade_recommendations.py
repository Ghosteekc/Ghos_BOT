"""Meta-backed upgrade priorities must remain grounded in their inputs."""

from __future__ import annotations

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


def test_priorities_use_active_deck_meta_and_arena_target() -> None:
    result = build_meta_upgrade_recommendations(
        _collection(),
        {"trophies": 2_000, "arena": {"id": 54_000_007, "name": "Royal Arena"}},
        _meta(),
    )

    assert result["status"] == "ok"
    assert result["arena"] == 7
    assert result["recommended_level"] == 8
    assert len(result["cards"]) == 5
    assert all(card["name"] in NAMES for card in result["cards"])
    assert all(card["recommended_level"] == 8 and card["deficit"] == 1 for card in result["cards"])


def test_priorities_fail_closed_without_reliable_meta() -> None:
    result = build_meta_upgrade_recommendations(
        _collection(),
        {"trophies": 2_000, "arena": {"id": 54_000_007, "name": "Royal Arena"}},
        _meta("stale"),
    )

    assert result["status"] == "meta_unavailable"
    assert result["cards"] == []
