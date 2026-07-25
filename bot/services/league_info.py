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
# Ranked entry after Challenger removal — classic API numbering.
ENTRY_LEAGUE_NUMBER = 4


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


def _player_trophies(player: dict) -> int:
    try:
        return int(player.get("trophies") or 0)
    except (TypeError, ValueError):
        return 0


def build_league_info(player: dict, *, now: date | None = None) -> dict:
    """Build league banner payload from Clash Royale player JSON.

    Display rules:
    - trophies < unlock threshold AND no Ranked season result → «opens at N cups»
    - otherwise show league (best/current, or Absolute Champion cups)
    """
    unlock_trophies = ranked_unlock_trophies(now)
    trophies = _player_trophies(player)

    current_num, current_cups = _season_league(player.get("currentPathOfLegendSeasonResult"))
    best_num, _ = _season_league(player.get("bestPathOfLegendSeasonResult"))

    # Also accept renamed / alternate payloads if Supercell adds them.
    if current_num is None:
        current_num, current_cups = _season_league(player.get("currentRankedSeasonResult"))
    if best_num is None:
        best_num, _ = _season_league(player.get("bestRankedSeasonResult"))

    has_league = current_num is not None or best_num is not None
    # Cups gate OR prior-season ticket / any Ranked progress.
    unlocked = trophies >= unlock_trophies or has_league

    if unlocked and not has_league:
        # Qualified by trophies but no season payload yet — Ranked starts at Master I.
        current_num = ENTRY_LEAGUE_NUMBER
        best_num = ENTRY_LEAGUE_NUMBER

    if best_num is None and current_num is not None:
        best_num = current_num
    if current_num is None and best_num is not None:
        current_num = best_num

    is_absolute = current_num == ABSOLUTE_CHAMPION_LEAGUE

    return {
        "unlocked": unlocked,
        "unlock_trophies": unlock_trophies,
        "current_league_number": current_num if unlocked else None,
        "current_league_name": league_name_ru(current_num) if unlocked else None,
        "current_league_icon": league_icon_url(current_num) if unlocked else None,
        "best_league_number": best_num if unlocked else None,
        "best_league_name": league_name_ru(best_num) if unlocked else None,
        "best_league_icon": league_icon_url(best_num) if unlocked else None,
        "is_absolute_champion": bool(unlocked and is_absolute),
        "absolute_trophies": current_cups if unlocked and is_absolute else None,
    }
