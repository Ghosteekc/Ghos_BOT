"""Deck hash, ranking and trend helpers for the Ghosteek meta collector.

Counting rule (conservative):
one observation = scanned player's deck from their battlelog.
Dedupe key is player_tag + battleTime + mode, so a repeat fetch of the same
log does not increment games. The opponent's copy of the same match is a
separate observation of a (usually different) deck.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

MODE_LEAGUE = "league"
MODE_TROPHIES = "trophies"
MODE_CLAN_WARS = "clan_wars"

LEAGUE_BATTLE_TYPES = frozenset({"pathoflegend"})
TROPHY_BATTLE_TYPES = frozenset({"pvp"})

TREND_UP_PCT = 12.0
TREND_DOWN_PCT = -12.0


def normalize_card_names(names: list[str]) -> list[str]:
    return [n.strip() for n in names if isinstance(n, str) and n.strip()]


def deck_hash_from_names(names: list[str]) -> str:
    cards = normalize_card_names(names)
    if len(cards) != 8:
        return ""
    return "|".join(sorted(cards))


def cards_csv(names: list[str]) -> str:
    return ",".join(normalize_card_names(names))


def observation_dedupe_key(player_tag: str, battle_time: str, mode: str) -> str:
    return f"{player_tag}|{battle_time}|{mode}"


def classify_battle_mode(battle: dict) -> str | None:
    from bot.services.battle_day_stats import is_ranked_1v1

    btype = str(battle.get("type") or "").lower().replace(" ", "")
    if is_ranked_1v1(battle) or btype in LEAGUE_BATTLE_TYPES:
        return MODE_LEAGUE
    if btype in TROPHY_BATTLE_TYPES:
        return MODE_TROPHIES
    return None


def battle_result(team: dict, opponent: dict) -> str:
    team_crowns = int(team.get("crowns") or 0)
    opp_crowns = int(opponent.get("crowns") or 0)
    if team_crowns > opp_crowns:
        return "win"
    if team_crowns < opp_crowns:
        return "loss"
    return "draw"


def parse_battle_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def utc_day(raw: str | None) -> str:
    dt = parse_battle_datetime(raw)
    if dt is None:
        return ""
    return dt.date().isoformat()


def wilson_lower_bound(wins: int, n: int, z: float = 1.64) -> float:
    """Lower bound of Wilson score interval — penalizes tiny samples."""
    if n <= 0:
        return 0.0
    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    spread = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    return max(0.0, (centre - spread) / denom)


def recency_factor(last_seen: datetime | None, now: datetime | None = None) -> float:
    if last_seen is None:
        return 0.3
    now = now or datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    age = now - last_seen
    if age <= timedelta(days=3):
        return 1.0
    if age <= timedelta(days=7):
        return 0.75
    if age <= timedelta(days=14):
        return 0.5
    return 0.25


def ranking_score(
    *,
    wins: int,
    games: int,
    unique_players: int,
    last_seen: datetime | None,
    max_games: int,
    now: datetime | None = None,
) -> float:
    if games <= 0:
        return 0.0
    del max_games
    wr_lb = wilson_lower_bound(wins, games)
    # Same win rate → more games ranks higher. Tiny hot streaks stay below
    # a large sample even if raw WR looks similar.
    volume = math.log(1.0 + games)
    players = min(1.0, unique_players / 8.0)
    fresh = recency_factor(last_seen, now)
    return round(wr_lb * volume * 0.88 + players * 0.04 + fresh * 0.08, 6)


def trend_from_counts(recent_games: int, previous_games: int) -> tuple[str, float | None]:
    """Return (up|stable|down, percent or None if not comparable)."""
    if previous_games <= 0 and recent_games <= 0:
        return "stable", None
    if previous_games <= 0:
        return "stable", None
    pct = (recent_games - previous_games) / previous_games * 100.0
    pct = round(pct, 1)
    if pct >= TREND_UP_PCT:
        return "up", pct
    if pct <= TREND_DOWN_PCT:
        return "down", pct
    return "stable", pct


def trend_from_history_values(
    values: list[int],
    *,
    history_days: int = 14,
) -> tuple[str, float | None]:
    """Match sparkline tail: last day vs previous day, then short-window slope."""
    if len(values) < 2:
        return "stable", None

    tail_len = min(7, len(values))
    tail = values[-tail_len:]
    if sum(tail) <= 0:
        return "stable", None

    last = tail[-1]
    prev = tail[-2]
    segment_threshold = max(1.0, prev * 0.15)

    if prev > 0:
        segment_change = last - prev
        if segment_change <= -segment_threshold:
            return "down", None
        if segment_change >= segment_threshold:
            return "up", None

    n = len(tail)
    sum_x = sum(range(n))
    sum_y = sum(tail)
    sum_xy = sum(i * value for i, value in enumerate(tail))
    sum_xx = sum(i * i for i in range(n))
    denom = n * sum_xx - sum_x * sum_x
    slope = (n * sum_xy - sum_x * sum_y) / denom if denom else 0.0
    slope_threshold = max(0.35, (sum_y / n) * 0.12)

    if slope >= slope_threshold:
        return "up", None
    if slope <= -slope_threshold:
        return "down", None
    return "stable", None
