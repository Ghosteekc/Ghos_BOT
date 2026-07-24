"""Tests for trophy growth / last_results selection."""

from bot.services.battle_day_stats import build_last_results, is_ladder_1v1


def _ladder(name: str, delta: int, *, crowns: int = 1, opp_crowns: int = 0, when: str = "20260724T120000.000Z") -> dict:
    return {
        "type": "PvP",
        "gameMode": {"name": "Ladder"},
        "battleTime": when,
        "team": [{
            "name": "Me",
            "tag": "#ME",
            "crowns": crowns,
            "trophyChange": delta,
            "startingTrophies": 5000,
            "cards": [],
        }],
        "opponent": [{
            "name": name,
            "tag": "#OPP",
            "crowns": opp_crowns,
            "startingTrophies": 5000,
            "cards": [],
        }],
    }


def test_is_ladder_requires_nonzero_trophy_change():
    assert is_ladder_1v1(_ladder("A", 30))
    assert not is_ladder_1v1(_ladder("A", 0))


def test_build_last_results_uses_newest_battles_not_oldest():
    # Newest-first log (Clash API order): 20 ladder battles.
    battles = [
        _ladder(f"Opp{i}", 30 if i % 2 == 0 else -28, when=f"20260724T{18 - i // 10}{i % 10}0000.000Z")
        for i in range(20)
    ]
    # Make the newest three distinctive.
    battles[0] = _ladder("Newest", -28, crowns=0, opp_crowns=1, when="20260724T184600.000Z")
    battles[1] = _ladder("Second", -28, crowns=0, opp_crowns=1, when="20260724T184100.000Z")
    battles[2] = _ladder("Third", 30, when="20260724T183000.000Z")
    battles[-1] = _ladder("Oldest", 99, when="20260720T100000.000Z")

    rows = build_last_results(battles, limit=5)

    assert len(rows) == 5
    assert rows[0]["opponent_name"] != "Oldest"
    assert rows[-1]["opponent_name"] == "Newest"
    assert rows[-1]["trophy_change"] == -28
    assert rows[-2]["opponent_name"] == "Second"
    assert rows[-3]["opponent_name"] == "Third"


def test_build_last_results_skips_missing_delta_and_fills_from_older():
    battles = [
        {
            "type": "PvP",
            "gameMode": {"name": "Ladder"},
            "battleTime": "20260724T180000.000Z",
            "team": [{
                "name": "Me",
                "tag": "#ME",
                "crowns": 1,
                "startingTrophies": 5100,
                "cards": [],
            }],
            "opponent": [{"name": "NoDelta", "crowns": 0, "startingTrophies": 5000, "cards": []}],
        },
        _ladder("WithDelta", -29, crowns=0, opp_crowns=1, when="20260724T170000.000Z"),
    ]
    rows = build_last_results(battles, limit=14)
    names = {r["opponent_name"] for r in rows}
    assert "WithDelta" in names
    assert any(r["opponent_name"] == "WithDelta" and r["trophy_change"] == -29 for r in rows)
