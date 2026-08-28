"""Mine decks list order: most recently played first."""
from __future__ import annotations

from bot.services.deck_analyzer import calculate_deck_winrates
from bot.services.mine_decks import deck_fingerprint


def _battle(time: str, names: list[str], *, tag: str = "#AAA") -> dict:
    cards = [{"name": n} for n in names]
    return {
        "type": "PvP",
        "battleTime": time,
        "team": [{"tag": tag, "cards": cards, "crowns": 1}],
        "opponent": [{"crowns": 0}],
    }


DECK_A = [
    "Hog Rider",
    "Ice Spirit",
    "Skeletons",
    "Cannon",
    "Musketeer",
    "Ice Golem",
    "The Log",
    "Fireball",
]
DECK_B = [
    "Giant",
    "Wizard",
    "Mini P.E.K.K.A",
    "Arrows",
    "Bomber",
    "Knight",
    "Archers",
    "Goblins",
]


def test_calculate_deck_winrates_tracks_last_seen():
    battles = [
        _battle("20260820T120000.000Z", DECK_A),
        _battle("20260828T180000.000Z", DECK_B),
        _battle("20260815T100000.000Z", DECK_A),
    ]
    winrates = calculate_deck_winrates(battles, "#AAA")
    key_a = deck_fingerprint(DECK_A)
    key_b = deck_fingerprint(DECK_B)
    assert winrates[key_a]["last_seen"] == "20260820T120000.000Z"
    assert winrates[key_b]["last_seen"] == "20260828T180000.000Z"


def test_mine_deck_rows_sort_newest_first():
    rows = [
        {"cards": DECK_A, "last_seen": "20260820T120000.000Z"},
        {"cards": DECK_B, "last_seen": "20260828T180000.000Z"},
    ]
    rows.sort(key=lambda row: row.get("last_seen") or "", reverse=True)
    assert deck_fingerprint(rows[0]["cards"]) == deck_fingerprint(DECK_B)
    assert deck_fingerprint(rows[1]["cards"]) == deck_fingerprint(DECK_A)
