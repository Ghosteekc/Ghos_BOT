from bot.services.league_info import build_league_info, LEAGUE_UNLOCK_TROPHIES


def test_league_locked():
    info = build_league_info({})
    assert info["unlocked"] is False
    assert info["unlock_trophies"] == LEAGUE_UNLOCK_TROPHIES
    assert info["is_absolute_champion"] is False


def test_league_unlocked_not_absolute():
    info = build_league_info(
        {
            "currentPathOfLegendSeasonResult": {"leagueNumber": 6, "trophies": 0},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 8, "trophies": 0},
        }
    )
    assert info["unlocked"] is True
    assert info["is_absolute_champion"] is False
    assert info["current_league_name"] == "Мастер III"
    assert info["best_league_name"] == "Великий чемпион"
    assert info["current_league_icon"].endswith("league6.png")
    assert info["absolute_trophies"] is None


def test_absolute_champion():
    info = build_league_info(
        {
            "currentPathOfLegendSeasonResult": {"leagueNumber": 10, "trophies": 2145},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 10, "trophies": 3000},
        }
    )
    assert info["unlocked"] is True
    assert info["is_absolute_champion"] is True
    assert info["current_league_name"] == "Абсолютный чемпион"
    assert info["absolute_trophies"] == 2145
