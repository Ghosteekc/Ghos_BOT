import asyncio
from types import SimpleNamespace

from bot.api.routes.battles import battle_history_info


class Session:
    def __init__(self, times):
        self.times = times

    async def execute(self, query):
        return self

    def scalars(self):
        return self

    def all(self):
        return self.times


def test_saved_history_bounds_include_legacy_rows_and_ignore_invalid_dates():
    user = SimpleNamespace(player_tag="#ABC")
    info = asyncio.run(battle_history_info(user, Session([
        "20260101T100000.000Z", "bad-old-row", "20250101T120000.000Z",
    ])))
    assert info == {
        "saved_battles": 3,
        "earliest_battle_at": "2025-01-01T12:00:00+00:00",
        "last_successful_sync_at": None,
    }


def test_empty_history_has_no_invented_dates():
    info = asyncio.run(battle_history_info(SimpleNamespace(player_tag="#ABC"), Session([])))
    assert info == {"saved_battles": 0, "earliest_battle_at": None, "last_successful_sync_at": None}
