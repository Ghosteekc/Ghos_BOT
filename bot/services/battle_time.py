"""Parse Clash Royale battleTime strings for UI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    try:
        _MSK = ZoneInfo("Europe/Moscow")
    except Exception:
        _MSK = timezone(timedelta(hours=3))
except ImportError:
    _MSK = timezone(timedelta(hours=3))


def format_battle_played_at(raw: str | None) -> str:
    """Return local time label like 19:22 from CR battleTime (UTC)."""
    if not raw:
        return ""
    try:
        dt = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(_MSK).strftime("%H:%M")
    except ValueError:
        return ""


def format_battle_played_date(raw: str | None) -> str:
    """Return date label like 03.07 from battleTime."""
    if not raw or len(raw) < 8:
        return ""
    try:
        dt = datetime.strptime(raw[:8], "%Y%m%d")
        return dt.strftime("%d.%m")
    except ValueError:
        return ""
