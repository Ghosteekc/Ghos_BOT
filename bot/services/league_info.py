"""Path of Legend / Ranked league helpers for player profile."""

from __future__ import annotations

# Ranked unlocks at 15k trophies this season (or Champion ticket from prior season).
LEAGUE_UNLOCK_TROPHIES = 15_000

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


def build_league_info(player: dict) -> dict:
    """Build league banner payload from Clash Royale player JSON."""
    current_num, current_cups = _season_league(player.get("currentPathOfLegendSeasonResult"))
    best_num, _ = _season_league(player.get("bestPathOfLegendSeasonResult"))

    unlocked = current_num is not None or best_num is not None
    is_absolute = current_num == ABSOLUTE_CHAMPION_LEAGUE

    return {
        "unlocked": unlocked,
        "unlock_trophies": LEAGUE_UNLOCK_TROPHIES,
        "current_league_number": current_num,
        "current_league_name": league_name_ru(current_num),
        "current_league_icon": league_icon_url(current_num),
        "best_league_number": best_num,
        "best_league_name": league_name_ru(best_num),
        "best_league_icon": league_icon_url(best_num),
        "is_absolute_champion": is_absolute,
        "absolute_trophies": current_cups if is_absolute else None,
    }
