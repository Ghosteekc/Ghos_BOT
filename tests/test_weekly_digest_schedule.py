"""Weekly digest schedule: Monday 11:00 MSK, stats Mon–Sun."""

from datetime import date, datetime, timedelta, timezone

from bot.services.weekly_digest import (
    iso_week_key,
    previous_completed_week,
    seconds_until_digest_wake,
    target_week_for_now,
    week_bounds,
)

MSK = timezone(timedelta(hours=3))


def _msk(y, m, d, h=0, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=MSK)


def test_week_bounds_are_monday_sunday():
    w = week_bounds("2026-W33")
    assert w.start.weekday() == 0  # Monday
    assert w.end.weekday() == 6  # Sunday
    assert (w.end - w.start).days == 6


def test_previous_completed_week_on_monday_is_yesterday_sunday():
    # Monday 2026-08-17 → 10.08–16.08, not the just-started 17.08–23.08
    window = previous_completed_week(_msk(2026, 8, 17, 8, 58))
    assert window.start == date(2026, 8, 10)
    assert window.end == date(2026, 8, 16)
    assert window.week_key == iso_week_key(date(2026, 8, 16))


def test_previous_completed_week_stays_closed_until_next_monday():
    expected = previous_completed_week(_msk(2026, 8, 17, 12))
    assert previous_completed_week(_msk(2026, 8, 18, 9)).week_key == expected.week_key
    assert previous_completed_week(_msk(2026, 8, 23, 23)).week_key == expected.week_key
    # Next Monday starts reporting the week that just ended
    nxt = previous_completed_week(_msk(2026, 8, 24, 8))
    assert nxt.start == date(2026, 8, 17)
    assert nxt.end == date(2026, 8, 23)


def test_monday_before_11_no_window():
    assert target_week_for_now(_msk(2026, 8, 17, 10, 59)) is None


def test_monday_from_11_targets_previous_week():
    # Monday 2026-08-17 11:00 → week of Sun 2026-08-16 = 2026-W33
    # ISO: 2026-08-10 Mon … 2026-08-16 Sun = W33
    now = _msk(2026, 8, 17, 11, 0)
    window = target_week_for_now(now)
    assert window is not None
    assert window.week_key == iso_week_key(date(2026, 8, 16))
    assert window.start == date(2026, 8, 10)
    assert window.end == date(2026, 8, 16)


def test_tuesday_wednesday_catchup_previous_week():
    mon_week = target_week_for_now(_msk(2026, 8, 17, 12))
    tue = target_week_for_now(_msk(2026, 8, 18, 9))
    wed = target_week_for_now(_msk(2026, 8, 19, 23))
    assert mon_week is not None and tue is not None and wed is not None
    assert mon_week.week_key == tue.week_key == wed.week_key
    assert mon_week.start.weekday() == 0
    assert mon_week.end.weekday() == 6


def test_sunday_no_longer_triggers():
    assert target_week_for_now(_msk(2026, 8, 16, 16, 0)) is None
    assert target_week_for_now(_msk(2026, 8, 16, 23, 0)) is None


def test_wake_sleeps_until_monday_11():
    # Thursday → next Monday 11:00
    now = _msk(2026, 8, 13, 15)  # Thu
    delay = seconds_until_digest_wake(now)
    target = _msk(2026, 8, 17, 11)
    assert abs(delay - (target - now).total_seconds()) < 2


def test_wake_monday_morning_until_11():
    now = _msk(2026, 8, 17, 8, 30)
    delay = seconds_until_digest_wake(now)
    assert 2 * 3600 < delay < 3 * 3600


def test_wake_during_send_window_hourly():
    assert seconds_until_digest_wake(_msk(2026, 8, 17, 11, 5)) == 3600.0
    assert seconds_until_digest_wake(_msk(2026, 8, 18, 14)) == 3600.0
