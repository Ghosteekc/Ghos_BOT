"""Meta collector: deck hash, ranking, trend, observation parsing."""

from datetime import datetime, timedelta, timezone

from bot.services.meta_observation import observation_from_battle
from bot.services.meta_stats import (
    battle_result,
    classify_battle_mode,
    deck_hash_from_names,
    observation_dedupe_key,
    ranking_score,
    trend_from_counts,
    trend_from_history_values,
    wilson_lower_bound,
)


def test_deck_hash_ignores_order():
    a = ["Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"]
    b = list(reversed(a))
    assert deck_hash_from_names(a) == deck_hash_from_names(b)
    assert deck_hash_from_names(a[:7]) == ""


def test_dedupe_key_is_stable_per_player_battle():
    key = observation_dedupe_key("#AAA", "20260818T120000.000Z", "league")
    assert key == observation_dedupe_key("#AAA", "20260818T120000.000Z", "league")
    assert key != observation_dedupe_key("#BBB", "20260818T120000.000Z", "league")


def test_wilson_small_sample_below_raw_winrate():
    raw = 8 / 10
    lb = wilson_lower_bound(8, 10)
    assert 0 < lb < raw


def test_ranking_prefers_volume_over_tiny_hot_streak():
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    last = now - timedelta(days=1)
    hot = ranking_score(wins=8, games=10, unique_players=2, last_seen=last, max_games=1000, now=now)
    solid = ranking_score(wins=600, games=1000, unique_players=40, last_seen=last, max_games=1000, now=now)
    assert solid > hot


def test_ranking_same_winrate_prefers_more_games():
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    last = now - timedelta(days=1)
    few = ranking_score(wins=80, games=100, unique_players=8, last_seen=last, max_games=500, now=now)
    many = ranking_score(wins=400, games=500, unique_players=8, last_seen=last, max_games=500, now=now)
    assert many > few


def test_trend_up_down_stable():
    assert trend_from_counts(24, 10)[0] == "up"
    assert trend_from_counts(10, 24)[0] == "down"
    assert trend_from_counts(11, 10)[0] == "stable"
    assert trend_from_counts(10, 0)[0] == "stable"


def test_trend_from_history_matches_sparkline_tail():
    assert trend_from_history_values([0, 0, 0, 0, 0, 0, 0, 2, 50, 4])[0] == "down"
    assert trend_from_history_values([1, 2, 4, 5, 6, 7, 8])[0] == "up"
    assert trend_from_history_values([5, 5, 5, 5, 5])[0] == "stable"


def test_classify_modes():
    assert classify_battle_mode({"type": "pathOfLegend", "team": [{}]}) == "league"
    assert classify_battle_mode({
        "type": "PvP",
        "gameMode": {"name": "Ranked1v1_NewArena"},
        "team": [{}],
    }) == "league"
    assert classify_battle_mode({
        "type": "PvP",
        "gameMode": {"name": "Ladder"},
        "team": [{}],
    }) == "trophies"
    assert classify_battle_mode({"type": "clanMate", "team": [{}]}) is None


def test_observation_skips_low_trophy_pvp():
    battle = {
        "type": "PvP",
        "battleTime": "20260818T120000.000Z",
        "team": [{
            "tag": "#AAA",
            "crowns": 1,
            "startingTrophies": 8000,
            "cards": [{"name": f"Card{i}"} for i in range(8)],
        }],
        "opponent": [{"tag": "#BBB", "crowns": 0}],
    }
    assert observation_from_battle("#AAA", battle, trophy_min=10000) is None


def test_observation_accepts_path_of_legend():
    names = ["Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"]
    battle = {
        "type": "pathOfLegend",
        "battleTime": "20260818T120000.000Z",
        "team": [{
            "tag": "#AAA",
            "crowns": 3,
            "startingTrophies": 0,
            "cards": [{"name": n} for n in names],
        }],
        "opponent": [{"tag": "#BBB", "crowns": 0}],
    }
    row = observation_from_battle("#AAA", battle, trophy_min=10000)
    assert row is not None
    assert row["mode"] == "league"
    assert row["result"] == "win"
    assert row["deck_hash"] == deck_hash_from_names(names)
    assert row["dedupe_key"] == observation_dedupe_key("#AAA", "20260818T120000.000Z", "league")


def test_observation_accepts_high_trophy_pvp():
    names = ["Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"]
    battle = {
        "type": "PvP",
        "gameMode": {"name": "Ladder"},
        "battleTime": "20260818T120000.000Z",
        "team": [{
            "tag": "#AAA",
            "crowns": 1,
            "startingTrophies": 12000,
            "cards": [{"name": n} for n in names],
        }],
        "opponent": [{"tag": "#BBB", "crowns": 0}],
    }
    row = observation_from_battle("#AAA", battle, trophy_min=10000)
    assert row is not None
    assert row["mode"] == "trophies"
    assert row["result"] == "win"


def test_ranked_pvp_is_not_trophies():
    names = ["Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"]
    battle = {
        "type": "PvP",
        "gameMode": {"name": "Ranked1v1_NewArena"},
        "battleTime": "20260818T120000.000Z",
        "team": [{
            "tag": "#AAA",
            "crowns": 1,
            "startingTrophies": 14000,
            "cards": [{"name": n} for n in names],
        }],
        "opponent": [{"tag": "#BBB", "crowns": 0}],
    }
    row = observation_from_battle("#AAA", battle, trophy_min=10000)
    assert row is not None
    assert row["mode"] == "league"


def test_battle_result_draw():
    assert battle_result({"crowns": 1}, {"crowns": 1}) == "draw"
