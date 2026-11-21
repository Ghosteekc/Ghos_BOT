"""Meta freshness must describe confirmed game data, not collector activity."""

import json
from datetime import datetime, timedelta, timezone

from bot.models.database import MetaDeckAggregate, MetaSnapshot
from bot.services.meta_query import (
    _freshness_message,
    _latest_confirmed_data_at,
    _snapshot_attempt,
)
from bot.services.meta_stats import battle_result


UTC = timezone.utc


def _snapshot(*, source: str = "cr_api", attempt: dict | None = None) -> MetaSnapshot:
    payload = {} if attempt is None else {"attempt": attempt}
    return MetaSnapshot(mode="league", source=source, payload_json=json.dumps(payload))


def test_confirmed_data_date_comes_from_observations_not_snapshot_attempt() -> None:
    old_battle = datetime(2026, 10, 20, 12, tzinfo=UTC)
    aggregate = MetaDeckAggregate(
        deck_hash="A",
        mode="league",
        total_games=10,
        last_seen=old_battle,
    )
    snap = _snapshot(attempt={"status": "no_new_data"})
    snap.created_at = datetime(2026, 11, 2, 12, tzinfo=UTC)

    assert _latest_confirmed_data_at([aggregate]) == old_battle
    assert snap.created_at > old_battle
    assert _snapshot_attempt(snap)["status"] == "no_new_data"


def test_collection_attempt_statuses_are_preserved() -> None:
    for status in ("complete", "no_new_data", "partial", "rate_limited", "failed", "no_data"):
        assert _snapshot_attempt(_snapshot(attempt={"status": status}))["status"] == status

    assert _snapshot_attempt(_snapshot(source="cr_api:429"))["status"] == "rate_limited"
    assert _snapshot_attempt(_snapshot(source="cr_api:error:503"))["status"] == "failed"


def test_freshness_messages_distinguish_partial_failure_and_no_new_data() -> None:
    old = datetime.now(UTC) - timedelta(days=2)

    assert _freshness_message(collection_status="partial", data_updated_at=old)[0] == "partial"
    assert _freshness_message(collection_status="rate_limited", data_updated_at=old)[0] == "rate_limited"
    assert _freshness_message(collection_status="failed", data_updated_at=old)[0] == "failed"
    assert _freshness_message(collection_status="no_new_data", data_updated_at=old)[0] == "no_new_data"
    assert _freshness_message(collection_status="complete", data_updated_at=old)[0] == "stale"


def test_meta_result_requires_complete_crown_data() -> None:
    assert battle_result({"crowns": 1}, {"crowns": 0}) == "win"
    assert battle_result({"crowns": 1}, {"crowns": 1}) == "draw"
    assert battle_result({}, {"crowns": 0}) == "unknown"
