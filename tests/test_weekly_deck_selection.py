from datetime import date

from bot.services.weekly_digest import WeekWindow, build_week_stats, format_digest_caption


WINDOW = WeekWindow("2026-W45", date(2026, 11, 2), date(2026, 11, 8))
DECK = ["Knight", "Archers", "Giant", "Musketeer", "Fireball", "Arrows", "Bomber", "Minions"]


def battle(deck, *, mode="PvP", crowns=1, opponent=0):
    return {
        "type": mode,
        "battleTime": "20261103T120000.000Z",
        "team": [{"tag": "#ME", "crowns": crowns, "cards": [{"name": c} for c in deck]}],
        "opponent": [{"crowns": opponent, "cards": []}],
    }


def test_selection_prefers_volume_until_twelve_then_winrate():
    other = DECK[:-1] + ["Skeletons"]
    for count in (1, 10, 12):
        stats = build_week_stats([battle(DECK, crowns=0, opponent=1)] * count + [battle(other)], "#ME", WINDOW)
        assert stats is not None
        assert set(stats.best_deck["cards"]) == set(other if count == 1 else DECK)
    stats = build_week_stats([battle(DECK, crowns=0, opponent=1)] * 12 + [battle(other)] * 12, "#ME", WINDOW)
    assert set(stats.best_deck["cards"]) == set(other)


def test_share_uses_same_eligible_deck_population_and_draws():
    other = DECK[:-1] + ["Skeletons"]
    battles = [battle(DECK), battle(DECK, crowns=1, opponent=1, mode="2v2"), battle(other, mode="pathOfLegend"), battle(other, mode="friendly"), battle(DECK[:3])]
    stats = build_week_stats(battles, "#ME", WINDOW)
    assert stats is not None
    assert stats.best_deck["total"] == 2
    assert stats.best_deck["winrate"] == 50.0
    assert stats.best_deck_share == 67.0
    assert "до 12" in format_digest_caption(stats)


def test_no_battles_and_no_complete_deck():
    assert build_week_stats([], "#ME", WINDOW) is None
    stats = build_week_stats([battle(DECK[:3])], "#ME", WINDOW)
    assert stats is not None
    assert stats.best_deck is None
    assert stats.best_deck_share == 0
