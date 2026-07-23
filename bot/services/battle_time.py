"""Parse Clash Royale battleTime strings for UI and persistence."""

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


def normalize_battle_time(raw: str | None) -> str | None:
    """Canonical battleTime/warTime string for DB keys and lookups.

    Clash Royale API returns timestamps like ``20250717T120000.000Z`` (UTC).
    There is no separate battle UUID — this string is the per-player dedup key.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("z"):
        text = f"{text[:-1]}Z"
    if len(text) >= 15 and "T" in text[:16]:
        return text
    return text


def battle_time_from_record(battle: dict) -> str | None:
    """Extract normalized battle time from a CR battlelog entry."""
    raw = battle.get("battleTime") or battle.get("warTime")
    return normalize_battle_time(raw if raw is not None else None)


def battle_times_equal(left: str | None, right: str | None) -> bool:
    left_norm = normalize_battle_time(left)
    right_norm = normalize_battle_time(right)
    return bool(left_norm and right_norm and left_norm == right_norm)


def battle_day_key(raw: str | None) -> str:
    """Calendar day key YYYYMMDD in Europe/Moscow."""
    if not raw:
        return ""
    try:
        if len(raw) >= 15 and "T" in raw[:16]:
            dt = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            return dt.astimezone(_MSK).strftime("%Y%m%d")
        if len(raw) >= 8:
            return raw[:8]
    except ValueError:
        pass
    return ""


def today_key_msk() -> str:
    return datetime.now(_MSK).strftime("%Y%m%d")


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
    """Return date label like 03.07 from battleTime (MSK)."""
    if not raw:
        return ""
    try:
        if len(raw) >= 15 and "T" in raw[:16]:
            dt = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            return dt.astimezone(_MSK).strftime("%d.%m")
        if len(raw) >= 8:
            dt = datetime.strptime(raw[:8], "%Y%m%d")
            return dt.strftime("%d.%m")
    except ValueError:
        pass
    return ""
