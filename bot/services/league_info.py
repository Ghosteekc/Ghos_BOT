"""Path of Legend / Ranked league helpers for player profile."""

from __future__ import annotations

from datetime import date, datetime, timezone

# Pre–July 2025 API: Challenger I … Ultimate Champion (1–10).
_LEAGUE_NAMES_LEGACY: dict[int, str] = {
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

# Current Ranked API (Challengers removed): Master I … Ultimate Champion (1–7).
_LEAGUE_NAMES_RANKED: dict[int, str] = {
    1: "Мастер I",
    2: "Мастер II",
    3: "Мастер III",
    4: "Чемпион",
    5: "Великий чемпион",
    6: "Королевский чемпион",
    7: "Абсолютный чемпион",
}

# New leagueNumber → RoyaleAPI arena/league{n}.png (old Master I … UC art).
_RANKED_ICON_INDEX: dict[int, int] = {
    1: 4,
    2: 5,
    3: 6,
    4: 7,
    5: 8,
    6: 9,
    7: 10,
}


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


LEAGUE_UNLOCK_TROPHIES = ranked_unlock_trophies()


def _season_league(result: object) -> tuple[int | None, int | None, int | None]:
    """Return (leagueNumber, trophies, rank)."""
    if not isinstance(result, dict):
        return None, None, None
    raw_num = result.get("leagueNumber")
    raw_trophies = result.get("trophies")
    raw_rank = result.get("rank")
    try:
        league_number = int(raw_num) if raw_num is not None else None
    except (TypeError, ValueError):
        league_number = None
    try:
        trophies = int(raw_trophies) if raw_trophies is not None else None
    except (TypeError, ValueError):
        trophies = None
    try:
        rank = int(raw_rank) if raw_rank is not None else None
    except (TypeError, ValueError):
        rank = None
    return league_number, trophies, rank


def _player_trophies(player: dict) -> int:
    try:
        return int(player.get("trophies") or 0)
    except (TypeError, ValueError):
        return 0


def _use_legacy_map(league_numbers: list[int]) -> bool:
    """Legacy 1–10 numbering if any season still reports > 7."""
    return any(n > 7 for n in league_numbers)


def _league_name(league_number: int | None, *, legacy: bool) -> str | None:
    if league_number is None:
        return None
    table = _LEAGUE_NAMES_LEGACY if legacy else _LEAGUE_NAMES_RANKED
    return table.get(int(league_number), f"Лига {league_number}")


def _league_icon(league_number: int | None, *, legacy: bool) -> str | None:
    if league_number is None:
        return None
    n = int(league_number)
    icon_n = n if legacy else _RANKED_ICON_INDEX.get(n, n)
    if icon_n < 0 or icon_n > 10:
        return None
    return f"https://royaleapi.github.io/cr-api-assets/arenas/league{icon_n}.png"


def _meaningful_ranked(
    current_num: int | None,
    current_cups: int | None,
    best_num: int | None,
    rank: int | None,
) -> bool:
    """True when Ranked progress is real — not a dormant leagueNumber=1 stub."""
    if (current_cups or 0) > 0:
        return True
    if rank is not None:
        return True
    if (current_num or 0) > 1 or (best_num or 0) > 1:
        return True
    return False


def build_league_info(player: dict, *, now: date | None = None) -> dict:
    """Build league banner payload from Clash Royale player JSON.

    Display rules:
    - below trophy gate and no real Ranked progress → «opens at N cups»
    - otherwise show best/current leagues (Absolute Champion shows purple cups)
    """
    unlock_trophies = ranked_unlock_trophies(now)
    trophies = _player_trophies(player)

    current_num, current_cups, current_rank = _season_league(
        player.get("currentPathOfLegendSeasonResult")
    )
    last_num, last_cups, _ = _season_league(player.get("lastPathOfLegendSeasonResult"))
    best_num, best_cups, _ = _season_league(player.get("bestPathOfLegendSeasonResult"))

    if current_num is None:
        current_num, current_cups, current_rank = _season_league(
            player.get("currentRankedSeasonResult")
        )
    if best_num is None:
        best_num, best_cups, _ = _season_league(player.get("bestRankedSeasonResult"))
    if last_num is None:
        last_num, last_cups, _ = _season_league(player.get("lastRankedSeasonResult"))

    # Prefer the highest known season for «best» when best payload is missing/low.
    for num, cups in ((last_num, last_cups), (current_num, current_cups)):
        if num is None:
            continue
        if best_num is None or num > best_num or (
            num == best_num and (cups or 0) > (best_cups or 0)
        ):
            best_num, best_cups = num, cups

    nums = [n for n in (current_num, best_num, last_num) if n is not None]
    legacy = _use_legacy_map(nums)
    absolute_n = 10 if legacy else 7
    entry_n = 4 if legacy else 1

    meaningful = _meaningful_ranked(current_num, current_cups, best_num, current_rank)
    unlocked = trophies >= unlock_trophies or meaningful

    if unlocked and current_num is None and best_num is None:
        current_num = entry_n
        best_num = entry_n

    if best_num is None and current_num is not None:
        best_num = current_num
    if current_num is None and best_num is not None:
        current_num = best_num

    is_absolute = unlocked and current_num == absolute_n

    return {
        "unlocked": unlocked,
        "unlock_trophies": unlock_trophies,
        "current_league_number": current_num if unlocked else None,
        "current_league_name": _league_name(current_num, legacy=legacy) if unlocked else None,
        "current_league_icon": _league_icon(current_num, legacy=legacy) if unlocked else None,
        "best_league_number": best_num if unlocked else None,
        "best_league_name": _league_name(best_num, legacy=legacy) if unlocked else None,
        "best_league_icon": _league_icon(best_num, legacy=legacy) if unlocked else None,
        "is_absolute_champion": bool(is_absolute),
        "absolute_trophies": current_cups if is_absolute else None,
    }
