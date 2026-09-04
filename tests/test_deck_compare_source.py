"""Deck comparison must use a deck the linked player actually played."""

from bot.api.routes.decks import _latest_played_user_deck


PLAYED_DECK = [
    "Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit",
    "Skeletons", "Cannon", "Fireball", "The Log",
]
OTHER_DECK = [
    "Giant", "Wizard", "Mini P.E.K.K.A", "Arrows",
    "Bomber", "Knight", "Archers", "Goblins",
]


def _battle(tag: str, cards: list[str]) -> dict:
    return {"team": [{"tag": tag, "cards": [{"name": card} for card in cards]}]}


def test_compare_uses_newest_played_deck_for_linked_player():
    latest = _latest_played_user_deck(
        [_battle("#OTHER", OTHER_DECK), _battle("#PLAYER", PLAYED_DECK)],
        "#PLAYER",
    )
    assert [card["name"] for card in latest] == PLAYED_DECK


def test_compare_never_falls_back_to_another_players_deck():
    assert _latest_played_user_deck([_battle("#OTHER", OTHER_DECK)], "#PLAYER") == []
