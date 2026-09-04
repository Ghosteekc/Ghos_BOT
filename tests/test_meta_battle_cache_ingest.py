from bot.models.database import BattleCache
from bot.services.meta_battle_cache_ingest import observation_from_battle_cache_row


def test_observation_from_battle_cache_row():
    row = BattleCache(
        player_tag="#AAA",
        battle_time="20260818T120000.000Z",
        result="win",
        user_deck="A,B,C,D,E,F,G,H",
        opponent_deck="",
        user_deck_json="",
        opponent_name="",
        opponent_tag="#BBB",
        trophy_change=30,
    )
    payload = observation_from_battle_cache_row(row)
    assert payload is not None
    assert payload["mode"] == "trophies"
    assert payload["source"] == "ghosteek_cache"


def test_observation_skips_non_ladder_cache_row():
    row = BattleCache(
        player_tag="#AAA",
        battle_time="20260818T120000.000Z",
        result="win",
        user_deck="A,B,C,D,E,F,G,H",
        opponent_deck="",
        user_deck_json="",
        opponent_name="",
        opponent_tag="#BBB",
        trophy_change=None,
    )
    assert observation_from_battle_cache_row(row) is None


def test_observation_skips_zero_trophy_delta_cache_row():
    row = BattleCache(
        player_tag="#aaa",
        battle_time="20260818T120000.000z",
        result="win",
        user_deck="A,B,C,D,E,F,G,H",
        opponent_deck="",
        user_deck_json="",
        opponent_name="",
        opponent_tag="#BBB",
        trophy_change=0,
    )
    assert observation_from_battle_cache_row(row) is None
