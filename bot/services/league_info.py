"""Path of Legend / Ranked league helpers for player profile."""

from __future__ import annotations

from datetime import date, datetime, timezone

# Official CR API still uses 1–10 (Challenger I … Ultimate Champion).
# Russian names match in-game «Абсолютный чемпион» for Ultimate Champion.
_LEAGUE_NAMES_RU: dict[int, str] = {
    1: "Претендент I",
    2: "Претендент II",
    3: "Претендент III",
    4: "Мастер I",
    5: "Мастер II",
    6: "Мастер III",
    7: "Чемпион",
    8: "Великий чемпион",
    9: "Королевский чемпион",
    10: "Абсолютный чемпион",
}

ABSOLUTE_CHAMPION_LEAGUE = 10


def ranked_unlock_trophies(now: date | None = None) -> int:
    """Trophy Road threshold to unlock Ranked this season.

    Source: Supercell «Update to Ranked Trophy Requirements» (14 Jul 2026):
    Jul–Aug 2026 → 13 000, Sep–Oct → 13 500, from Nov → 14 000.
    Ranked also unlocks via Champion (or higher) finish in the previous season.
    """
    d = now or datetime.now(timezone.utc).date()
    if d < date(2026, 9, 1):
        return 13_000
    if d < date(2026, 11, 1):
        return 13_500
    return 14_000


# Back-compat alias for tests / imports
LEAGUE_UNLOCK_TROPHIES = ranked_unlock_trophies()


def league_name_ru(league_number: int | None) -> str | None:
    if league_number is None:
        return None
    return _LEAGUE_NAMES_RU.get(int(league_number), f"Лига {league_number}")


def league_icon_url(league_number: int | None) -> str | None:
    if league_number is None:
        return None
    n = int(league_number)
    if n < 0 or n > 10:
        return None
    return f"https://royaleapi.github.io/cr-api-assets/arenas/league{n}.png"


def _season_league(result: object) -> tuple[int | None, int | None]:
    if not isinstance(result, dict):
        return None, None
    raw_num = result.get("leagueNumber")
    raw_trophies = result.get("trophies")
    try:
        league_number = int(raw_num) if raw_num is not None else None
    except (TypeError, ValueError):
        league_number = None
    try:
        trophies = int(raw_trophies) if raw_trophies is not None else None
    except (TypeError, ValueError):
        trophies = None
    return league_number, trophies


def build_league_info(player: dict, *, now: date | None = None) -> dict:
    """Build league banner payload from Clash Royale player JSON."""
    unlock_trophies = ranked_unlock_trophies(now)
    current_num, current_cups = _season_league(player.get("currentPathOfLegendSeasonResult"))
    best_num, _ = _season_league(player.get("bestPathOfLegendSeasonResult"))

    # Unlocked if CR already returned a Ranked season result (trophy threshold
    # or previous-season Champion ticket). Trophy count alone is not enough —
    # a player can sit above the threshold without entering Ranked yet.
    unlocked = current_num is not None or best_num is not None
    is_absolute = current_num == ABSOLUTE_CHAMPION_LEAGUE

    return {
        "unlocked": unlocked,
        "unlock_trophies": unlock_trophies,
        "current_league_number": current_num,
        "current_league_name": league_name_ru(current_num),
        "current_league_icon": league_icon_url(current_num),
        "best_league_number": best_num,
        "best_league_name": league_name_ru(best_num),
        "best_league_icon": league_icon_url(best_num),
        "is_absolute_champion": is_absolute,
        "absolute_trophies": current_cups if is_absolute else None,
    }
