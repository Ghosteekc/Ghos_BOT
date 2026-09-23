"""Mode labels must reflect only confirmed battle-log fields."""

from bot.services.battle_mode import battle_mode_label


def _battle(*, battle_type: str = "PvP", mode: str = "Ladder") -> dict:
    return {
        "type": battle_type,
        "gameMode": {"name": mode},
        "team": [{"trophyChange": 30}],
    }


def test_labels_known_non_ranked_modes():
    assert battle_mode_label(_battle()) == "Кубки"
    assert battle_mode_label(_battle(battle_type="2v2", mode="2v2")) == "2 на 2"
    assert battle_mode_label(_battle(battle_type="trail", mode="TeamVsTeam")) == "2 на 2"
    assert battle_mode_label(_battle(mode="ClassicDeck")) == "Классика"
    assert battle_mode_label(_battle(battle_type="challenge", mode="Challenge")) == "Испытание"


def test_ranked_uses_existing_league_mark_without_duplicate_label():
    assert battle_mode_label(_battle(battle_type="pathOfLegend", mode="Ranked1v1_NewArena")) is None


def test_unknown_mode_is_not_guessed():
    assert battle_mode_label(_battle(mode="FutureMode")) == "Режим не указан"
