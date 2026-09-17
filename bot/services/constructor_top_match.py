"""Match constructor card picks against cached top-player decks."""

from __future__ import annotations

import asyncio
from datetime import datetime

from bot.services.meta_analyzer import _guess_deck_name
from bot.services.meta_query import get_ladder_meta
from bot.services.meta_stats import MODE_LEAGUE, MODE_TROPHIES
from bot.services.top_players import MAX_TOP_PLAYERS_LIMIT, get_top_players


def _deck_names(cards: list[dict]) -> frozenset[str]:
    return frozenset(c["name"] for c in cards if c.get("name"))


def _selected_names(card_names: list[str]) -> set[str]:
    return {name.strip() for name in card_names if name and name.strip()}


def _safe_limit(limit: int) -> int:
    return max(1, min(int(limit), 50))


def match_top_decks_from_players(
    players: list[dict],
    card_names: list[str],
    *,
    limit: int = 30,
) -> list[dict]:
    """Pure matcher: decks from top players that contain all selected cards."""
    selected = _selected_names(card_names)
    if not selected:
        return []
    if len(selected) > 4:
        return []

    safe_limit = _safe_limit(limit)
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


def match_meta_decks(
    meta_results: list[dict],
    card_names: list[str],
    *,
    limit: int = 50,
) -> list[dict]:
    """Pure matcher for persisted meta decks from both supported ladder modes."""
    selected = _selected_names(card_names)
    if not selected or len(selected) > 4:
        return []

    groups: dict[frozenset[str], dict] = {}
    labels = {MODE_LEAGUE: "Лига", MODE_TROPHIES: "Кубки"}
    for meta in meta_results:
        mode = str(meta.get("mode") or "")
        for deck in meta.get("decks") or []:
            cards = deck.get("cards") or []
            if len(cards) != 8:
                continue
            names = _deck_names(cards)
            if len(names) != 8 or not selected.issubset(names):
                continue

            group = groups.setdefault(
                names,
                {
                    "cards": cards,
                    "deck_link": deck.get("deck_link"),
                    "total_games": 0,
                    "weighted_wr": 0.0,
                    "player_count": 0,
                    "modes": [],
                },
            )
            games = int(deck.get("games_count") or 0)
            winrate = float(deck.get("win_rate") or 0.0)
            group["total_games"] += games
            group["weighted_wr"] += winrate * games
            group["player_count"] += int(deck.get("unique_players") or 0)
            label = labels.get(mode, "Мета")
            if label not in group["modes"]:
                group["modes"].append(label)

    rows: list[dict] = []
    for names, group in groups.items():
        cards = group["cards"]
        total_games = group["total_games"]
        avg_elixir = round(sum(float(card.get("cost") or 0) for card in cards) / 8, 1)
        rows.append(
            {
                "cards": cards,
                "name": _guess_deck_name(sorted(names)) or "Метовая колода",
                "winrate": round(group["weighted_wr"] / total_games, 1) if total_games else 0.0,
                "total_games": total_games,
                "avg_elixir": avg_elixir,
                "deck_link": group["deck_link"],
                "description": f"Мета · {', '.join(group['modes'])}",
                "best_rank": 9999,
                "player_count": group["player_count"],
                "matched_cards": sorted(selected),
            }
        )

    rows.sort(key=lambda row: (-row["total_games"], -row["winrate"]))
    return rows[:_safe_limit(limit)]


def merge_constructor_decks(
    top_decks: list[dict],
    meta_decks: list[dict],
    *,
    limit: int = 30,
) -> list[dict]:
    """Merge sources by card set, keeping one grounded candidate per deck."""
    merged: dict[frozenset[str], dict] = {}
    for deck in [*top_decks, *meta_decks]:
        key = _deck_names(deck.get("cards") or [])
        if len(key) != 8:
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(deck)
            continue
        if deck.get("description", "").startswith("Мета"):
            existing["description"] = f"{existing['description']} · Мета"

    rows = list(merged.values())
    rows.sort(key=lambda row: (-row["total_games"], -row["winrate"], row["best_rank"]))
    for index, row in enumerate(rows[:_safe_limit(limit)], start=1):
        row["id"] = index
    return rows[:_safe_limit(limit)]


async def match_constructor_top_decks(
    card_names: list[str],
    *,
    limit: int = 30,
) -> dict:
    cache = await get_top_players(limit=MAX_TOP_PLAYERS_LIMIT)
    meta_requests = await asyncio.gather(
        get_ladder_meta(MODE_LEAGUE),
        get_ladder_meta(MODE_TROPHIES),
        return_exceptions=True,
    )
    top_decks = match_top_decks_from_players(cache.players, card_names, limit=50)
    meta_decks = match_meta_decks(
        [result for result in meta_requests if isinstance(result, dict)],
        card_names,
        limit=50,
    )
    decks = merge_constructor_decks(top_decks, meta_decks, limit=limit)
    updated_at = cache.updated_at.isoformat() if isinstance(cache.updated_at, datetime) else None
    return {"decks": decks, "updated_at": updated_at}
