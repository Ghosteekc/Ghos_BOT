"""Tests for constructor top-deck matching."""

from bot.services.constructor_top_match import match_top_decks_from_players


def _player(rank: int, name: str, deck: list[str], *, games: int = 10, wr: float = 60.0):
    cards = [{"name": c, "slot": i, "cost": 4, "icon": ""} for i, c in enumerate(deck)]
    return {
        "rank": rank,
        "player_name": name,
        "cards": cards,
        "total_games": games,
        "winrate": wr,
        "avg_elixir": 3.5,
        "deck_link": "https://link.clashroyale.com/deck/en?deck=1",
    }


def test_match_requires_all_selected_cards():
    players = [
        _player(1, "A", ["Hog Rider", "Fireball", "Ice Spirit", "Cannon", "Skeletons", "Log", "Musketeer", "Ice Golem"]),
        _player(2, "B", ["Giant", "Fireball", "Ice Spirit", "Cannon", "Skeletons", "Log", "Musketeer", "Mini PEKKA"]),
    ]
    matched = match_top_decks_from_players(players, ["Hog Rider", "Fireball"])
    assert len(matched) == 1
    assert matched[0]["best_rank"] == 1
    assert matched[0]["total_games"] == 10


def test_match_dedupes_same_deck():
    deck = ["Hog Rider", "Fireball", "Ice Spirit", "Cannon", "Skeletons", "Log", "Musketeer", "Ice Golem"]
    players = [
        _player(1, "A", deck, games=10, wr=60.0),
        _player(5, "B", deck, games=20, wr=70.0),
    ]
    matched = match_top_decks_from_players(players, ["Hog Rider"])
    assert len(matched) == 1
    assert matched[0]["total_games"] == 30
    assert matched[0]["winrate"] == 66.7
    assert matched[0]["player_count"] == 2


def test_match_sorts_by_games_then_winrate():
    deck_a = ["Hog Rider", "Fireball", "Ice Spirit", "Cannon", "Skeletons", "Log", "Musketeer", "Ice Golem"]
    deck_b = ["Hog Rider", "Earthquake", "Ice Spirit", "Cannon", "Skeletons", "Log", "Musketeer", "Ice Golem"]
    players = [
        _player(3, "Low", deck_a, games=5, wr=90.0),
        _player(1, "High", deck_b, games=50, wr=55.0),
    ]
    matched = match_top_decks_from_players(players, ["Hog Rider"])
    assert len(matched) == 2
    assert matched[0]["total_games"] == 50
    assert matched[1]["total_games"] == 5
