"""Daily battle aggregates for profile and analytics."""

from __future__ import annotations

from datetime import datetime

from bot.services.battle_time import battle_day_key, today_key_msk


def _battle_won(battle: dict) -> bool:
    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]
    return team.get("crowns", 0) > opponent.get("crowns", 0)


def _battle_time(battle: dict) -> str:
    return str(battle.get("battleTime") or battle.get("warTime") or "")


def compute_daily_trophy_change(battles: list) -> int:
    """Net trophies gained or lost today (MSK)."""
    today = today_key_msk()
    total = 0
    for battle in battles:
        raw = _battle_time(battle)
        if battle_day_key(raw) != today:
            continue
        team = battle.get("team", [{}])[0]
        total += int(team.get("trophyChange") or 0)
    return total


def _daily_winrate(wins: int, losses: int) -> float:
    total = wins + losses
    if total <= 0:
        return 0.0
    return round(wins / total * 100, 1)


def build_winrate_by_day(battles: list, *, limit: int = 14) -> list[dict]:
    """Daily wins/losses and winrate percentage for each day."""
    by_day: dict[str, dict[str, int]] = {}

    for battle in battles:
        raw = _battle_time(battle)
        day_key = battle_day_key(raw)
        if not day_key:
            continue

        won = _battle_won(battle)
        entry = by_day.setdefault(day_key, {"wins": 0, "losses": 0})
        if won:
            entry["wins"] += 1
        else:
            entry["losses"] += 1

    rows: list[dict] = []
    for day_key, data in sorted(by_day.items()):
        wins = data["wins"]
        losses = data["losses"]
        rows.append({
            "date": datetime.strptime(day_key, "%Y%m%d").strftime("%d.%m"),
            "wins": wins,
            "losses": losses,
            "winrate": _daily_winrate(wins, losses),
        })

    return rows[-limit:]
