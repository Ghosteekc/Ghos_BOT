"""Daily battle aggregates for profile and analytics."""

from __future__ import annotations

from datetime import datetime

from bot.services.battle_time import battle_day_key, today_key_msk

_LADDER_1V1_TYPES = frozenset({"pvp", "pathoflegend"})


def _normalize_battle_type(raw: str | None) -> str:
    return (raw or "").strip().lower().replace(" ", "")


def is_ladder_1v1(battle: dict) -> bool:
    """Ladder 1v1 battles that award trophies (excludes 2v2 and casual modes)."""
    team = battle.get("team") or []
    if len(team) != 1:
        return False
    return _normalize_battle_type(battle.get("type")) in _LADDER_1V1_TYPES


def _battle_won(battle: dict) -> bool:
    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]
    return team.get("crowns", 0) > opponent.get("crowns", 0)


def _battle_time(battle: dict) -> str:
    return str(battle.get("battleTime") or battle.get("warTime") or "")


def _trophy_delta(team: dict, chronological: list[dict], index: int) -> int | None:
    raw = team.get("trophyChange")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass

    cur_start = team.get("startingTrophies")
    if index + 1 < len(chronological):
        nxt_team = chronological[index + 1].get("team", [{}])[0]
        nxt_start = nxt_team.get("startingTrophies")
        if cur_start is not None and nxt_start is not None:
            return int(nxt_start) - int(cur_start)

    return None


def build_last_results(battles: list, *, limit: int = 14) -> list[dict]:
    """Recent ladder 1v1 battles oldest-first with trophy delta and opponent/time labels."""
    from bot.services.battle_time import format_battle_played_at, format_battle_played_date

    ladder = [b for b in battles if is_ladder_1v1(b)]
    chronological = list(reversed(ladder))
    rows: list[dict] = []

    for i, battle in enumerate(chronological):
        if len(rows) >= limit:
            break
        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        delta = _trophy_delta(team, chronological, i)
        if delta is None:
            continue
        won = _battle_won(battle)
        raw = _battle_time(battle)
        rows.append({
            "won": won,
            "trophy_change": delta,
            "opponent_name": opponent.get("name") or "Соперник",
            "played_date": format_battle_played_date(raw),
            "played_time": format_battle_played_at(raw),
        })

    return rows


def compute_daily_trophy_change(battles: list) -> int:
    """Net trophies gained or lost today (MSK) from ladder 1v1 only."""
    today = today_key_msk()
    total = 0
    for battle in battles:
        if not is_ladder_1v1(battle):
            continue
        raw = _battle_time(battle)
        if battle_day_key(raw) != today:
            continue
        team = battle.get("team", [{}])[0]
        delta = team.get("trophyChange")
        if delta is None:
            continue
        total += int(delta)
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
