"""Match constructor card picks against cached top-player decks."""

from __future__ import annotations

from datetime import datetime

from bot.services.meta_analyzer import _guess_deck_name
from bot.services.top_players import get_top_players


def _deck_names(cards: list[dict]) -> frozenset[str]:
    return frozenset(c["name"] for c in cards if c.get("name"))


def match_top_decks_from_players(
    players: list[dict],
    card_names: list[str],
    *,
    limit: int = 30,
) -> list[dict]:
    """Pure matcher: decks from top players that contain all selected cards."""
    selected = {n.strip() for n in card_names if n and n.strip()}
    if not selected:
        return []
    if len(selected) > 4:
        return []

    safe_limit = max(1, min(int(limit), 50))
    groups: dict[frozenset[str], dict] = {}

    for player in players:
        cards = player.get("cards") or []
        if len(cards) != 8:
            continue
        names = _deck_names(cards)
        if len(names) != 8 or not selected.issubset(names):
            continue

        if names not in groups:
            groups[names] = {
                "cards": cards,
                "deck_link": player.get("deck_link"),
                "avg_elixir": float(player.get("avg_elixir") or 0.0),
                "total_games": 0,
                "weighted_wr": 0.0,
                "best_rank": int(player.get("rank") or 9999),
                "player_names": [],
            }

        group = groups[names]
        games = int(player.get("total_games") or 0)
        winrate = float(player.get("winrate") or 0.0)
        group["total_games"] += games
        group["weighted_wr"] += winrate * games
        group["best_rank"] = min(group["best_rank"], int(player.get("rank") or 9999))
        pname = (player.get("player_name") or "").strip()
        if pname and pname not in group["player_names"]:
            group["player_names"].append(pname)

    rows: list[dict] = []
    for names, group in groups.items():
        total_games = group["total_games"]
        winrate = round(group["weighted_wr"] / total_games, 1) if total_games else 0.0
        player_names: list[str] = group["player_names"]
        players_label = ", ".join(player_names[:3])
        if len(player_names) > 3:
            players_label = f"{players_label} +{len(player_names) - 3}"
        rank = group["best_rank"]
        description = f"Топ-{rank}"
        if players_label:
            description = f"{description} · {players_label}"

        deck_name = _guess_deck_name(sorted(names)) or "Колода топов"
        rows.append(
            {
                "cards": group["cards"],
                "name": deck_name,
                "winrate": winrate,
                "total_games": total_games,
                "avg_elixir": group["avg_elixir"],
                "deck_link": group["deck_link"],
                "description": description,
                "best_rank": rank,
                "player_count": len(player_names),
                "matched_cards": sorted(selected),
            }
        )

    rows.sort(
        key=lambda r: (
            -r["total_games"],
            -r["winrate"],
            r["best_rank"],
        )
    )
    for idx, row in enumerate(rows[:safe_limit], start=1):
        row["id"] = idx
    return rows[:safe_limit]


async def match_constructor_top_decks(
    card_names: list[str],
    *,
    limit: int = 30,
) -> dict:
    cache = await get_top_players(limit=100)
    decks = match_top_decks_from_players(cache.players, card_names, limit=limit)
    updated_at = cache.updated_at.isoformat() if isinstance(cache.updated_at, datetime) else None
    return {"decks": decks, "updated_at": updated_at}
