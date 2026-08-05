"""Path of Legend / Ranked league helpers for player profile."""

from __future__ import annotations

from datetime import date, datetime, timezone

# Current Ranked (Challengers removed July 2025): Master I … Ultimate Champion (1–7).
_LEAGUE_NAMES_RANKED: dict[int, str] = {
    1: "Мастер I",
    2: "Мастер II",
    3: "Мастер III",
    4: "Чемпион",
    5: "Великий чемпион",
    6: "Королевский чемпион",
    7: "Абсолютный чемпион",
}

# Ranked 1..7 → RoyaleAPI arenas/league{n}.png
# league1–3 = старые «Претендент» (два меча) — больше не отдаём.
# league4–10 = Мастер I … Абсолютный чемпион (актуальный арт: молот, банка молнии, …).
_RANKED_ICON_INDEX: dict[int, int] = {
    1: 4,  # Master I
    2: 5,  # Master II
    3: 6,  # Master III (lightning bottle)
    4: 7,  # Champion
    5: 8,  # Grand Champion
    6: 9,  # Royal Champion
    7: 10,  # Ultimate Champion
}

_ICON_CDN = "https://royaleapi.github.io/cr-api-assets/arenas"


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


def _to_ranked_number(league_number: int | None) -> int | None:
    """Normalize API leagueNumber to Ranked scale 1..7.

    New API (post-Challenger): 1=Master I … 7=Ultimate Champion.
    Legacy ids 8–10 (Grand/Royal/Ultimate on old 1–10 scale) → 5–7.
    Values 1–7 stay as Ranked — never remap to removed Challenger I–III.
    """
    if league_number is None:
        return None
    n = int(league_number)
    if n > 7:
        return max(1, min(7, n - 3))
    if n < 1:
        return None
    return min(7, n)


def _league_name(ranked_number: int | None) -> str | None:
    if ranked_number is None:
        return None
    return _LEAGUE_NAMES_RANKED.get(int(ranked_number), f"Лига {ranked_number}")


def _league_icon(ranked_number: int | None) -> str | None:
    """Master+ art only (league4–10). Never Challenger swords (league1–3)."""
    if ranked_number is None:
        return None
    icon_n = _RANKED_ICON_INDEX.get(int(ranked_number))
    if icon_n is None:
        return None
    return f"{_ICON_CDN}/league{icon_n}.png"


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


def _better_season(
    a_num: int | None,
    a_cups: int | None,
    b_num: int | None,
    b_cups: int | None,
) -> tuple[int | None, int | None]:
    """Return the stronger of two normalized seasons."""
    if b_num is None:
        return a_num, a_cups
    if a_num is None or b_num > a_num or (
        b_num == a_num and (b_cups or 0) > (a_cups or 0)
    ):
        return b_num, b_cups
    return a_num, a_cups


def build_league_info(player: dict, *, now: date | None = None) -> dict:
    """Build league banner payload from Clash Royale player JSON.

    Display rules:
    - below trophy gate and no real Ranked progress → «opens at N cups»
    - otherwise show best/current leagues (Absolute Champion shows purple cups)
    - names/icons always on post-Challenger Ranked scale (no sword badges)
    """
    unlock_trophies = ranked_unlock_trophies(now)
    trophies = _player_trophies(player)

    current_raw, current_cups, current_rank = _season_league(
        player.get("currentPathOfLegendSeasonResult")
    )
    last_raw, last_cups, _ = _season_league(player.get("lastPathOfLegendSeasonResult"))
    best_raw, best_cups, _ = _season_league(player.get("bestPathOfLegendSeasonResult"))

    if current_raw is None:
        current_raw, current_cups, current_rank = _season_league(
            player.get("currentRankedSeasonResult")
        )
    if best_raw is None:
        best_raw, best_cups, _ = _season_league(player.get("bestRankedSeasonResult"))
    if last_raw is None:
        last_raw, last_cups, _ = _season_league(player.get("lastRankedSeasonResult"))

    current_num = _to_ranked_number(current_raw)
    last_num = _to_ranked_number(last_raw)
    best_num = _to_ranked_number(best_raw)

    best_num, best_cups = _better_season(best_num, best_cups, last_num, last_cups)
    best_num, best_cups = _better_season(best_num, best_cups, current_num, current_cups)

    absolute_n = 7
    entry_n = 1

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
        "current_league_name": _league_name(current_num) if unlocked else None,
        "current_league_icon": _league_icon(current_num) if unlocked else None,
        "best_league_number": best_num if unlocked else None,
        "best_league_name": _league_name(best_num) if unlocked else None,
        "best_league_icon": _league_icon(best_num) if unlocked else None,
        "is_absolute_champion": bool(is_absolute),
        "absolute_trophies": current_cups if is_absolute else None,
    }
