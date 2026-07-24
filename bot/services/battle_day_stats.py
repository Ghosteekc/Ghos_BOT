"""Daily battle aggregates for profile and analytics."""

from __future__ import annotations

from datetime import datetime, timedelta

from bot.services.battle_time import battle_day_key, battle_time_from_record, today_key_msk

_LADDER_1V1_TYPES = frozenset({"pvp", "pathoflegend"})
_EXCLUDED_BATTLE_TYPES = frozenset({
    "trail",
    "twovstwo",
    "2v2",
    "clanmate",
    "friendly",
    "tournament",
    "challenge",
    "warday",
    "boatbattle",
    "cached",
})
_LADDER_GAME_MODES = frozenset({"ladder", "pathoflegend", "seasonal", "ranked"})


def _normalize_battle_type(raw: str | None) -> str:
    return (raw or "").strip().lower().replace(" ", "")


def _game_mode_key(battle: dict) -> str:
    raw = battle.get("gameMode")
    name = ""
    if isinstance(raw, dict):
        name = str(raw.get("name") or raw.get("id") or "")
    elif raw is not None:
        name = str(raw)
    return _normalize_battle_type(name)


def is_ladder_1v1(battle: dict) -> bool:
    """Ladder 1v1 battles that award trophies (excludes 2v2, classic, casual)."""
    team = battle.get("team") or []
    if len(team) != 1:
        return False

    battle_type = _normalize_battle_type(battle.get("type"))
    if battle_type in _EXCLUDED_BATTLE_TYPES:
        return False
    if battle_type not in _LADDER_1V1_TYPES:
        return False
    if _is_casual_game_mode(battle):
        return False

    mode_key = _game_mode_key(battle)
    if battle_type == "pvp" and mode_key and mode_key not in _LADDER_GAME_MODES:
        return False

    trophy_change = team[0].get("trophyChange")
    if trophy_change is not None:
        try:
            return int(trophy_change) != 0
        except (TypeError, ValueError):
            return False

    # Older/partial payloads: still count as ladder if trophies are present.
    return team[0].get("startingTrophies") is not None


def _is_casual_game_mode(battle: dict) -> bool:
    raw = battle.get("gameMode")
    name = ""
    if isinstance(raw, dict):
        name = str(raw.get("name") or raw.get("id") or "")
    elif raw is not None:
        name = str(raw)
    key = _normalize_battle_type(name)
    if not key:
        return False
    casual_markers = (
        "casual",
        "classic",
        "2v2",
        "touchdown",
        "draft",
        "dual",
        "river",
        "rampage",
        "challenge",
        "clan",
        "war",
        "boat",
        "friendly",
    )
    return any(marker in key for marker in casual_markers)


def _battle_won(battle: dict) -> bool:
    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]
    return team.get("crowns", 0) > opponent.get("crowns", 0)


def _battle_time(battle: dict) -> str:
    return battle_time_from_record(battle) or ""


def _trophy_delta(team: dict, chronological: list[dict], index: int) -> int | None:
    """Trophy delta from API field, or from consecutive startingTrophies."""
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


def compute_daily_trophy_change(battles: list) -> int | None:
    """Net trophies gained or lost today (MSK) from ladder 1v1 only."""
    today = today_key_msk()
    total = 0
    counted = 0
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
        counted += 1
    if counted == 0:
        return None
    return total


def _daily_winrate(wins: int, losses: int) -> float:
    total = wins + losses
    if total <= 0:
        return 0.0
    return round(wins / total * 100, 1)


def build_winrate_by_day(battles: list, *, days: int = 14) -> list[dict]:
    """Daily wins/losses and winrate for the last N calendar days (MSK).

    Always returns exactly ``days`` rows, including days without battles.
    """
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

    today = datetime.strptime(today_key_msk(), "%Y%m%d").date()
    rows: list[dict] = []
    for offset in range(days - 1, -1, -1):
        day_key = (today - timedelta(days=offset)).strftime("%Y%m%d")
        data = by_day.get(day_key, {"wins": 0, "losses": 0})
        wins = data["wins"]
        losses = data["losses"]
        rows.append({
            "date": datetime.strptime(day_key, "%Y%m%d").strftime("%d.%m"),
            "wins": wins,
            "losses": losses,
            "winrate": _daily_winrate(wins, losses),
        })

    return rows


def build_most_used_cards(battles: list, player_tag: str, *, limit: int = 6) -> list[dict]:
    """Top cards by usage with per-card winrate from battle log."""
    from bot.services.clash_api import normalize_tag

    tag_norm = normalize_tag(player_tag)
    stats: dict[str, dict[str, int]] = {}
    for battle in battles:
        team = battle.get("team", [{}])[0]
        if team.get("tag") and normalize_tag(team.get("tag", "")) != tag_norm:
            continue
        opponent = battle.get("opponent", [{}])[0]
        won = team.get("crowns", 0) > opponent.get("crowns", 0)
        for card in team.get("cards", []):
            name = card.get("name")
            if not name:
                continue
            entry = stats.setdefault(name, {"count": 0, "wins": 0})
            entry["count"] += 1
            if won:
                entry["wins"] += 1

    rows: list[dict] = []
    for name, data in sorted(stats.items(), key=lambda item: item[1]["count"], reverse=True)[:limit]:
        count = data["count"]
        winrate = round(data["wins"] / count * 100, 1) if count else 0.0
        rows.append({"name": name, "count": count, "winrate": winrate})
    return rows
