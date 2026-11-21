"""Meta API exposes the actual Ghosteek sample period without filtering it."""

from __future__ import annotations

from datetime import datetime, timezone

from bot.api.schemas import MetaLadderResponse
from bot.models.database import MetaDeckAggregate
from bot.services.meta_query import _confirmed_sample_period


UTC = timezone.utc


def test_confirmed_period_uses_aggregate_observation_bounds() -> None:
    earlier = datetime(2026, 9, 1, 10, tzinfo=UTC)
    latest = datetime(2026, 11, 2, 12, tzinfo=UTC)
    rows = [
        MetaDeckAggregate(deck_hash="A", mode="trophies", first_seen=earlier, last_seen=latest),
        MetaDeckAggregate(
            deck_hash="B",
            mode="trophies",
            first_seen=datetime(2026, 10, 1, tzinfo=UTC),
            last_seen=datetime(2026, 10, 5, tzinfo=UTC),
        ),
    ]

    assert _confirmed_sample_period(rows) == (earlier, latest)


def test_confirmed_period_does_not_invent_unknown_dates() -> None:
    start, end = _confirmed_sample_period([
        MetaDeckAggregate(deck_hash="legacy", mode="league", first_seen=None, last_seen=None),
    ])

    assert start is None
    assert end is None


def test_confirmed_period_retains_old_observations_without_a_new_window() -> None:
    old = datetime(2025, 1, 5, 8, tzinfo=UTC)
    recent = datetime(2026, 11, 2, 12, tzinfo=UTC)

    assert _confirmed_sample_period([
        MetaDeckAggregate(deck_hash="old", mode="league", first_seen=old, last_seen=recent),
    ]) == (old, recent)


def test_ladder_api_contract_marks_sample_as_cumulative() -> None:
    response = MetaLadderResponse(
        mode="trophies",
        status="partial",
        message="Собрана только часть источников.",
        sample_note="Источник: Ghosteek, не глобальная статистика Clash Royale.",
        updated_at="2026-11-02T12:00:00+00:00",
        attempted_at="2026-11-02T12:05:00+00:00",
        collection_status="partial",
        sample_started_at="2026-09-01T10:00:00+00:00",
        last_battle_at="2026-11-02T12:00:00+00:00",
        is_cumulative=True,
        sample_origin="ghosteek_observations",
        min_games=5,
        decks=[],
    )

    payload = response.model_dump()
    assert payload["is_cumulative"] is True
    assert payload["sample_started_at"] == "2026-09-01T10:00:00+00:00"
    assert payload["last_battle_at"] == "2026-11-02T12:00:00+00:00"
    assert payload["collection_status"] == "partial"
