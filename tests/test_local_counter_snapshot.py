"""Regression checks for the self-contained counter database."""

from __future__ import annotations

from bot.services.local_counter_data import load_local_counter_snapshot


def test_counter_snapshot_is_local_and_keeps_all_card_relations() -> None:
    counters, source, status = load_local_counter_snapshot()

    assert status.available is True
    assert len(counters) == 122
    assert source["storage"] == "local_snapshot"
    assert "site" not in source
    assert all("url" not in card_data for card_data in counters.values())
