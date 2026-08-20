from bot.services.clan_war_decks import (
    CW_BATTLE_TYPES,
    _deck_names_from_cw_battle,
    _guess_cw_role,
    load_clan_war_snapshot,
)


def test_clan_war_snapshot_empty_is_unavailable():
    snap = load_clan_war_snapshot()
    assert snap["available"] is False
    assert snap["decks"] == []
    assert snap["source"] == ""
    assert "КВ" in (snap["message"] or "")


def test_cw_curated_fallback_decks():
    from bot.services.clan_war_decks import _curated_cw_decks

    decks = _curated_cw_decks()
    assert len(decks) >= 4
    assert all(len(item["cards"]) == 8 for item in decks)


def test_cw_battle_types_and_deck_parse():
    assert "warday" in CW_BATTLE_TYPES
    names = [f"Card{i}" for i in range(8)]
    battle = {
        "type": "warDay",
        "team": [{"cards": [{"name": n} for n in names]}],
    }
    assert _deck_names_from_cw_battle(battle) == names
    assert _guess_cw_role(names) in {"Натиск", "Цикл", "Контроль", "Универсал"}
