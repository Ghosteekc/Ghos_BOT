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


def build_winrate_by_day(battles: list, *, limit: int = 14) -> list[dict]:
    """Daily wins/losses plus winrate from the last battle of each day."""
    by_day: dict[str, dict] = {}

    for battle in battles:
        raw = _battle_time(battle)
        day_key = battle_day_key(raw)
        if not day_key:
            continue

        won = _battle_won(battle)
        entry = by_day.setdefault(
            day_key,
            {"wins": 0, "losses": 0, "last_time": "", "last_battle_won": None},
        )
        if won:
            entry["wins"] += 1
        else:
            entry["losses"] += 1

        if raw >= entry["last_time"]:
            entry["last_time"] = raw
            entry["last_battle_won"] = won

    rows: list[dict] = []
    for day_key, data in sorted(by_day.items()):
        last_won = data["last_battle_won"]
        winrate = 100.0 if last_won else 0.0
        rows.append({
            "date": datetime.strptime(day_key, "%Y%m%d").strftime("%d.%m"),
            "wins": data["wins"],
            "losses": data["losses"],
            "winrate": winrate,
        })

    return rows[-limit:]
