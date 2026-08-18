from bot.services.clan_war_decks import load_clan_war_snapshot


def test_clan_war_snapshot_empty_is_unavailable():
    snap = load_clan_war_snapshot()
    assert snap["available"] is False
    assert snap["decks"] == []
    assert snap["source"] == ""
    assert "КВ" in (snap["message"] or "")
