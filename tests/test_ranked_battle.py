from bot.services.battle_day_stats import is_ranked_1v1, ranked_battle_sides
from bot.services.league_info import infer_ranked_number_from_score


def _ranked(
    *,
    league_number=None,
    user_league=None,
    opp_league=None,
    user_cups=14,
    opp_cups=43,
    trophy_change=6,
    battle_type="pathOfLegend",
    mode="Ranked1v1_NewArena",
    team_size=1,
):
    team = {
        "name": "Me",
        "crowns": 1,
        "trophyChange": trophy_change,
        "startingTrophies": user_cups,
        "cards": [],
    }
    if user_league is not None:
        team["leagueNumber"] = user_league
    opp = {
        "name": "Opp",
        "crowns": 0,
        "startingTrophies": opp_cups,
        "cards": [],
    }
    if opp_league is not None:
        opp["leagueNumber"] = opp_league
    battle = {
        "type": battle_type,
        "gameMode": {"name": mode},
        "team": [team] * team_size,
        "opponent": [opp],
    }
    if league_number is not None:
        battle["leagueNumber"] = league_number
    return battle


def test_path_of_legend_is_ranked():
    assert is_ranked_1v1(_ranked())


def test_ranked_game_mode_is_ranked():
    assert is_ranked_1v1(_ranked(battle_type="PvP", mode="Ranked1v1_NewArena"))


def test_pvp_ladder_is_not_ranked_even_with_league_number():
    battle = _ranked(battle_type="PvP", mode="Ladder", league_number=4)
    assert not is_ranked_1v1(battle)
    is_ranked, user, opp = ranked_battle_sides(battle)
    assert is_ranked is False
    assert user is None
    assert opp is None


def test_2v2_is_not_ranked():
    assert not is_ranked_1v1(_ranked(team_size=2))


def test_infer_ranked_steps():
    assert infer_ranked_number_from_score(0, 6) == 1
    assert infer_ranked_number_from_score(11, 6) == 2
    assert infer_ranked_number_from_score(22, -6) == 3
    assert infer_ranked_number_from_score(33, 6) == 4
    assert infer_ranked_number_from_score(43, 6) == 5
    assert infer_ranked_number_from_score(53, 6) == 6
    assert infer_ranked_number_from_score(63, 6) == 7


def test_infer_legacy_path_of_legend_cups():
    assert infer_ranked_number_from_score(4000, 30) == 7
    assert infer_ranked_number_from_score(2500, 30) == 4
    assert infer_ranked_number_from_score(14000, 30) is None


def test_user_fallback_to_battle_league_opponent_does_not():
    is_ranked, user, opp = ranked_battle_sides(
        _ranked(league_number=4, user_cups=14000, opp_cups=14000, trophy_change=6)
    )
    assert is_ranked is True
    assert user["league_name"] == "Чемпион"
    assert user["league_icon"].endswith("league7.png")
    assert opp is None


def test_opponent_league_inferred_from_ranked_steps():
    is_ranked, user, opp = ranked_battle_sides(
        _ranked(league_number=5, user_cups=14000, opp_cups=43, trophy_change=6)
    )
    assert is_ranked is True
    assert user["league_name"] == "Великий чемпион"
    assert opp["league_name"] == "Великий чемпион"
    assert opp["league_number"] == 5


def test_opponent_league_from_own_number_not_battle_fallback():
    is_ranked, user, opp = ranked_battle_sides(
        _ranked(league_number=7, user_league=7, opp_league=2, user_cups=63, opp_cups=11)
    )
    assert is_ranked is True
    assert user["league_name"] == "Абсолютный чемпион"
    assert opp["league_name"] == "Мастер II"
    assert opp["league_icon"].endswith("league5.png")
