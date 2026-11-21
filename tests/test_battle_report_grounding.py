"""Battle reports distinguish crown facts from deck-composition estimates."""

from bot.services.battle_report import analyze_battle_enhanced
from bot.services.battle_cache_reader import row_to_battle_dict
from bot.services.battle_service import build_battle_cache_row


USER = [
    "Hog Rider", "Ice Golem", "Cannon", "Musketeer",
    "Ice Spirit", "Skeletons", "The Log", "Fireball",
]
OPPONENT = [
    "Lava Hound", "Balloon", "Baby Dragon", "Mega Minion",
    "Tombstone", "Arrows", "Zap", "Miner",
]


def _side(cards: list[str], crowns: int | None) -> dict:
    side = {"cards": [{"name": card} for card in cards]}
    if crowns is not None:
        side["crowns"] = crowns
    return side


def test_loss_keeps_crown_fact_but_never_invents_play_or_damage() -> None:
    report = analyze_battle_enhanced(_side(USER, 0), _side(OPPONENT, 1), duration=120)
    text = " ".join([report.outcome_summary, *report.reasons]).lower()

    assert report.outcome == "loss"
    assert report.outcome_summary.startswith("Поражение по коронам.")
    assert "по составу" in text
    assert "не была нейтрализована" not in text
    assert "нанесла больше всего" not in text
    assert "сыграл слабо" not in text
    assert "быстрее циклил" not in text


def test_win_labels_pressure_as_potential_not_recorded_damage() -> None:
    report = analyze_battle_enhanced(_side(USER, 1), _side(OPPONENT, 0), duration=100)

    assert report.outcome == "win"
    assert report.outcome_summary.startswith("Победа по коронам.")
    assert all("потенциаль" in item.note.lower() for item in report.user_key_cards)
    assert "нанес" not in report.outcome_summary.lower()


def test_draw_is_not_misreported_as_a_loss() -> None:
    report = analyze_battle_enhanced(_side(USER, 1), _side(OPPONENT, 1))

    assert report.outcome == "draw"
    assert report.won is False
    assert report.outcome_summary.startswith("Ничья по коронам.")


def test_incomplete_decks_do_not_produce_matchup_or_card_claims() -> None:
    report = analyze_battle_enhanced(_side(USER[:3], 0), _side(OPPONENT[:4], None))

    assert report.outcome == "unknown"
    assert "Колоды неполные" in report.outcome_summary
    assert report.user_key_cards == []
    assert report.opponent_key_cards == []
    assert report.low_impact_cards == []
    assert report.match_difficulty is None
    assert report.tactical_matchup is None


def test_draw_is_preserved_through_battle_cache() -> None:
    battle = {
        "battleTime": "20261102T120000.000Z",
        "team": [_side(USER, 1)],
        "opponent": [_side(OPPONENT, 1)],
    }
    row = build_battle_cache_row(battle, "#PLAYER")

    assert row is not None
    assert row["result"] == "draw"

    class CachedRow:
        result = "draw"
        user_deck_json = ""
        user_deck = ",".join(USER)
        opponent_deck = ",".join(OPPONENT)
        opponent_name = "Opponent"
        opponent_tag = "#OPP"
        trophy_change = None
        battle_type = "PvP"
        game_mode = "Ladder"
        battle_time = "20261102T120000.000Z"

    restored = row_to_battle_dict(CachedRow(), "#PLAYER")
    assert restored["team"][0]["crowns"] == restored["opponent"][0]["crowns"]
