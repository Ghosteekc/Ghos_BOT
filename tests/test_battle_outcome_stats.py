"""Regression coverage for confirmed win/loss/draw/unknown battle outcomes."""

from datetime import date

from bot.services.battle_cache_reader import row_to_battle_dict
from bot.services.battle_day_stats import build_winrate_by_day
from bot.services.battle_service import build_battle_cache_row
from bot.services.deck_analyzer import battle_outcome, calculate_deck_winrates
from bot.services.weekly_digest import WeekWindow, build_week_stats


DECK = ["Knight", "Archers", "Giant", "Musketeer", "Fireball", "Arrows", "Bomber", "Minions"]


def _battle(user_crowns: int | None, opponent_crowns: int | None, *, mode: str = "PvP") -> dict:
    team = {"tag": "#ME", "cards": [{"name": card} for card in DECK]}
    opponent = {"tag": "#OP", "cards": [{"name": card} for card in DECK]}
    if user_crowns is not None:
        team["crowns"] = user_crowns
    if opponent_crowns is not None:
        opponent["crowns"] = opponent_crowns
    return {
        "type": mode,
        "gameMode": {"name": "Ladder"},
        "battleTime": "20261102T120000.000Z",
        "team": [team],
        "opponent": [opponent],
    }


def test_outcome_requires_explicit_crown_values() -> None:
    assert battle_outcome(_battle(2, 1)["team"][0], _battle(2, 1)["opponent"][0]) == "win"
    assert battle_outcome(_battle(0, 1)["team"][0], _battle(0, 1)["opponent"][0]) == "loss"
    assert battle_outcome(_battle(1, 1)["team"][0], _battle(1, 1)["opponent"][0]) == "draw"
    assert battle_outcome(_battle(None, 1)["team"][0], _battle(None, 1)["opponent"][0]) == "unknown"


def test_deck_winrate_counts_draw_but_excludes_unknown() -> None:
    battles = [_battle(1, 0), _battle(0, 1), _battle(1, 1), _battle(None, 0)]
    for index, battle in enumerate(battles):
        battle["battleTime"] = f"20261102T120{index}00.000Z"

    row = next(iter(calculate_deck_winrates(battles, "#ME").values()))

    assert row["wins"] == 1
    assert row["losses"] == 1
    assert row["draws"] == 1
    assert row["unknowns"] == 1
    assert row["total"] == 4
    assert row["scored_games"] == 3
    assert row["winrate"] == 33.3


def test_daily_and_weekly_stats_preserve_draw_and_unknown(monkeypatch) -> None:
    monkeypatch.setattr("bot.services.battle_day_stats.today_key_msk", lambda: "20261102")
    battles = [_battle(1, 0), _battle(0, 1), _battle(1, 1), _battle(None, 0)]
    daily = build_winrate_by_day(battles, days=1)[0]
    assert (daily["wins"], daily["losses"], daily["draws"], daily["unknowns"]) == (1, 1, 1, 1)
    assert daily["scored_games"] == 3
    assert daily["winrate"] == 33.3

    weekly = build_week_stats(
        battles,
        "#ME",
        WeekWindow("2026-W45", date(2026, 11, 2), date(2026, 11, 8)),
    )
    assert weekly is not None
    assert (weekly.wins, weekly.losses, weekly.draws, weekly.unknowns) == (1, 1, 1, 1)
    assert weekly.scored_games == 3
    assert weekly.winrate == 33.3


def test_new_draw_is_saved_but_legacy_loss_is_not_rewritten_by_a_guess() -> None:
    new_draw = build_battle_cache_row(_battle(1, 1), "#ME")
    assert new_draw is not None
    assert new_draw["result"] == "draw"

    class LegacyLoss:
        result = "loss"
        user_deck_json = ""
        user_deck = ",".join(DECK)
        opponent_deck = ",".join(DECK)
        opponent_name = "Opponent"
        opponent_tag = "#OP"
        trophy_change = None
        battle_type = "cached"
        game_mode = ""
        battle_time = "20250101T120000.000Z"

    restored = row_to_battle_dict(LegacyLoss(), "#ME")
    assert restored["team"][0]["crowns"] < restored["opponent"][0]["crowns"]


def test_team_battle_keeps_the_side_crown_result_after_normalization() -> None:
    from bot.services.battle_service import normalize_battle_for_player

    raw = {
        "type": "2v2",
        "team": [
            {"tag": "#ALLY", "crowns": 3, "cards": []},
            {"tag": "#OTHER", "crowns": 3, "cards": []},
        ],
        "opponent": [
            {"tag": "#ME", "crowns": 1, "cards": []},
            {"tag": "#ALLY2", "crowns": 1, "cards": []},
        ],
    }
    battle = normalize_battle_for_player(raw, "#ME")
    assert battle is not None
    assert battle_outcome(battle["team"][0], battle["opponent"][0]) == "loss"
