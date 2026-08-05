from datetime import date

from bot.services.league_info import build_league_info, ranked_unlock_trophies


def test_ranked_unlock_schedule():
    assert ranked_unlock_trophies(date(2026, 7, 26)) == 13_000
    assert ranked_unlock_trophies(date(2026, 8, 31)) == 13_000
    assert ranked_unlock_trophies(date(2026, 9, 1)) == 13_500
    assert ranked_unlock_trophies(date(2026, 10, 15)) == 13_500
    assert ranked_unlock_trophies(date(2026, 11, 1)) == 14_000


def test_below_gate_dormant_league_stub_shows_unlock_text():
    """Ghosteek-style: <13k cups, leagueNumber=1, 0 rated cups → still locked."""
    info = build_league_info(
        {
            "trophies": 12_014,
            "currentPathOfLegendSeasonResult": {"leagueNumber": 1, "trophies": 0, "rank": None},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 1, "trophies": 0, "rank": None},
        },
        now=date(2026, 7, 26),
    )
    assert info["unlocked"] is False
    assert info["unlock_trophies"] == 13_000
    assert info["current_league_name"] is None


def test_absolute_champion_new_ranked_numbering():
    """Basim-style: leagueNumber 7 + purple cups = Абсолютный чемпион (not old «Чемпион»)."""
    info = build_league_info(
        {
            "trophies": 14_000,
            "currentPathOfLegendSeasonResult": {"leagueNumber": 7, "trophies": 2944, "rank": 47},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 7, "trophies": 3676, "rank": 21},
        },
        now=date(2026, 7, 26),
    )
    assert info["unlocked"] is True
    assert info["is_absolute_champion"] is True
    assert info["current_league_name"] == "Абсолютный чемпион"
    assert info["best_league_name"] == "Абсолютный чемпион"
    assert info["absolute_trophies"] == 2944
    assert info["current_league_icon"].endswith("league10.png")


def test_master_ii_new_numbering():
    info = build_league_info(
        {
            "trophies": 13_500,
            "currentPathOfLegendSeasonResult": {"leagueNumber": 2, "trophies": 0},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 3, "trophies": 0},
        },
        now=date(2026, 7, 26),
    )
    assert info["unlocked"] is True
    assert info["current_league_name"] == "Мастер II"
    assert info["best_league_name"] == "Мастер III"
    assert info["current_league_icon"].endswith("league5.png")
    assert info["best_league_icon"].endswith("league6.png")
    assert info["is_absolute_champion"] is False


def test_legacy_best_uc_does_not_force_challenger_icons():
    """Historical best=10 (old UC) + current=1 (new Master I) must not show Претендент/swords."""
    info = build_league_info(
        {
            "trophies": 14_000,
            "currentPathOfLegendSeasonResult": {"leagueNumber": 1, "trophies": 0},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 10, "trophies": 2100},
        },
        now=date(2026, 8, 5),
    )
    assert info["unlocked"] is True
    assert info["current_league_name"] == "Мастер I"
    assert info["best_league_name"] == "Абсолютный чемпион"
    assert info["current_league_number"] == 1
    assert info["best_league_number"] == 7
    assert info["current_league_icon"].endswith("league4.png")
    assert info["best_league_icon"].endswith("league10.png")
    assert "league1.png" not in (info["current_league_icon"] or "")
    assert "Претендент" not in (info["current_league_name"] or "")


def test_master_iii_uses_lightning_bottle_icon():
    info = build_league_info(
        {
            "trophies": 14_000,
            "currentPathOfLegendSeasonResult": {"leagueNumber": 3, "trophies": 0},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 3, "trophies": 0},
        },
        now=date(2026, 8, 5),
    )
    assert info["current_league_name"] == "Мастер III"
    assert info["current_league_icon"].endswith("league6.png")


def test_legacy_ultimate_only_best():
    info = build_league_info(
        {
            "trophies": 14_000,
            "currentPathOfLegendSeasonResult": {"leagueNumber": 3, "trophies": 0},
            "bestPathOfLegendSeasonResult": {"leagueNumber": 10, "trophies": 2100},
        },
        now=date(2026, 8, 5),
    )
    assert info["current_league_name"] == "Мастер III"
    assert info["best_league_name"] == "Абсолютный чемпион"
    assert info["best_league_icon"].endswith("league10.png")
