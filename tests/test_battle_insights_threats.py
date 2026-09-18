"""Recurring loss threats stay grounded in the deck actually played."""

from types import SimpleNamespace

from bot.services import battle_insights


def _battle(*, user_cards: list[str], opponent_cards: list[str]) -> dict:
    return {
        "battleTime": "20260918T120000.000Z",
        "team": [{"tag": "#PLAYER", "crowns": 0, "cards": user_cards}],
        "opponent": [{"name": "Opponent", "crowns": 1, "cards": opponent_cards}],
    }


def test_loss_threats_count_recurring_cards_and_keep_played_deck_counter(monkeypatch) -> None:
    monkeypatch.setattr(battle_insights, "extract_deck", lambda side: list(side["cards"]))
    monkeypatch.setattr(
        battle_insights,
        "analyze_battle_list_item",
        lambda *_args, **_kwargs: SimpleNamespace(opponent_threats=["Tesla"]),
    )
    monkeypatch.setattr(
        battle_insights,
        "counters_in_deck",
        lambda _threat, deck: (["Earthquake"], []) if "Earthquake" in deck else ([], []),
    )
    monkeypatch.setattr(
        battle_insights,
        "_tactical_lines",
        lambda _user, _opponent: ["Дави после того, как Tesla раскрыта."],
    )

    deck_with_answer = ["Hog Rider", "Earthquake", "Ice Golem", "Cannon", "The Log", "Musketeer", "Ice Spirit", "Skeletons"]
    deck_without_answer = ["Hog Rider", "Fireball", "Valkyrie", "Cannon", "The Log", "Musketeer", "Ice Spirit", "Skeletons"]
    rows = battle_insights.build_loss_threats(
        [
            _battle(user_cards=deck_with_answer, opponent_cards=["Tesla"] * 8),
            _battle(user_cards=deck_without_answer, opponent_cards=["Tesla"] * 8),
        ],
        "#PLAYER",
    )

    assert len(rows) == 1
    assert rows[0]["card"] == "Tesla"
    assert rows[0]["losses"] == 2
    # The newest loss used Earthquake, so the displayed answer is truthful for
    # the representative played deck rather than borrowed from another deck.
    assert rows[0]["counter_status"] == "strong"
    assert rows[0]["strong_counters"]
    assert rows[0]["tactics"] == ["Дави после того, как Tesla раскрыта."]


def test_loss_threats_mark_missing_counter_without_inventing_one(monkeypatch) -> None:
    monkeypatch.setattr(battle_insights, "extract_deck", lambda side: list(side["cards"]))
    monkeypatch.setattr(
        battle_insights,
        "analyze_battle_list_item",
        lambda *_args, **_kwargs: SimpleNamespace(opponent_threats=["P.E.K.K.A"]),
    )
    monkeypatch.setattr(battle_insights, "counters_in_deck", lambda *_args: ([], []))
    monkeypatch.setattr(battle_insights, "_tactical_lines", lambda *_args: [])

    rows = battle_insights.build_loss_threats(
        [_battle(user_cards=["Hog Rider"] * 8, opponent_cards=["P.E.K.K.A"] * 8)],
        "#PLAYER",
    )

    assert rows[0]["counter_status"] == "missing"
    assert rows[0]["strong_counters"] == []
    assert rows[0]["partial_counters"] == []


def test_loss_threats_excludes_wins_and_draws(monkeypatch) -> None:
    monkeypatch.setattr(battle_insights, "extract_deck", lambda side: list(side["cards"]))
    monkeypatch.setattr(
        battle_insights,
        "analyze_battle_list_item",
        lambda *_args, **_kwargs: SimpleNamespace(opponent_threats=["Tesla"]),
    )

    draw = _battle(user_cards=["Hog Rider"] * 8, opponent_cards=["Tesla"] * 8)
    draw["opponent"][0]["crowns"] = 0
    win = _battle(user_cards=["Hog Rider"] * 8, opponent_cards=["Tesla"] * 8)
    win["team"][0]["crowns"] = 2

    assert battle_insights.build_loss_threats([draw, win], "#PLAYER") == []
