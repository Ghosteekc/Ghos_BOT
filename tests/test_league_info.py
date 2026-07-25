from datetime import date

from bot.services.league_info import build_league_info, ranked_unlock_trophies


def test_ranked_unlock_schedule():
    assert ranked_unlock_trophies(date(2026, 7, 26)) == 13_000
    assert ranked_unlock_trophies(date(2026, 8, 31)) == 13_000
    assert ranked_unlock_trophies(date(2026, 9, 1)) == 13_500
    assert ranked_unlock_trophies(date(2026, 10, 15)) == 13_500
    assert ranked_unlock_trophies(date(2026, 11, 1)) == 14_000


def test_league_locked_below_threshold():
    info = build_league_info({"trophies": 12_000}, now=date(2026, 7, 26))
    assert info["unlocked"] is False
    assert info["unlock_trophies"] == 13_000
    assert info["is_absolute_champion"] is False
    assert info["current_league_name"] is None


def test_league_unlocked_by_trophies_without_season_payload():
    info = build_league_info({"trophies": 14_000}, now=date(2026, 7, 26))
    assert info["unlocked"] is True
    assert info["current_league_name"] == "Мастер I"
    assert info["best_league_name"] == "Мастер I"
    assert info["is_absolute_champion"] is False


def test_league_unlocked_not_absolute():
    info = build_league_info(
        {
            "trophies": 9_000,
            "currentPathOfLegendSeasonResult": {"leagueNumber": 6, "trophies": 0},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 8, "trophies": 0},
        },
        now=date(2026, 7, 26),
    )
    assert info["unlocked"] is True
    assert info["is_absolute_champion"] is False
    assert info["current_league_name"] == "Мастер III"
    assert info["best_league_name"] == "Великий чемпион"
    assert info["current_league_icon"].endswith("league6.png")
    assert info["absolute_trophies"] is None
    assert info["unlock_trophies"] == 13_000


def test_absolute_champion():
    info = build_league_info(
        {
            "trophies": 15_000,
            "currentPathOfLegendSeasonResult": {"leagueNumber": 10, "trophies": 2145},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 10, "trophies": 3000},
        },
        now=date(2026, 7, 26),
    )
    assert info["unlocked"] is True
    assert info["is_absolute_champion"] is True
    assert info["current_league_name"] == "Абсолютный чемпион"
    assert info["absolute_trophies"] == 2145
