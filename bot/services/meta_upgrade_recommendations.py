"""Upgrade priorities grounded in the player's deck and persisted meta sample."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from bot.services.deck_level_advisor import (
    recommended_display_level,
    resolve_player_arena_number,
)


def build_meta_upgrade_recommendations(
    collection: dict[str, Any],
    player: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Return upgrade priorities without fabricating meta or resource facts.

    A card is eligible only when it is in both the confirmed API currentDeck and
    a reliable persisted Trophy Road meta deck. The target is the pre-existing
    arena level threshold, capped by the card's API-provided maximum level.
    """
    arena_data = player.get("arena") or {}
    trophies = int(player.get("trophies") or 0)
    arena_id = arena_data.get("id")
    arena_name = arena_data.get("name")
    arena = resolve_player_arena_number(
        trophies=trophies,
        arena_id=int(arena_id) if arena_id is not None else None,
        arena_name=str(arena_name) if arena_name else None,
    )
    target_level = recommended_display_level(
        trophies=trophies,
        arena_id=int(arena_id) if arena_id is not None else None,
        arena_name=str(arena_name) if arena_name else None,
    )

    base = {
        "arena": arena,
        "recommended_level": target_level,
        "updated_at": meta.get("updated_at"),
        "sample_note": meta.get("sample_note") or "",
        "cards": [],
    }
    if meta.get("status") != "ok":
        return {
            **base,
            "status": "meta_unavailable",
            "message": meta.get("message") or "Недостаточно актуальных данных меты.",
        }

    active_deck = list(collection.get("current_deck") or [])
    if len(active_deck) != 8:
        return {
            **base,
            "status": "deck_unavailable",
            "message": "API не вернул полную экипированную колоду игрока.",
        }

    # Aggregate only facts carried by the persisted, ranked meta deck payload.
    appearances: dict[str, dict[str, int]] = defaultdict(
        lambda: {"meta_deck_count": 0, "observed_games": 0, "wins": 0}
    )
    for deck in meta.get("decks") or []:
        names = {
            str(card.get("name") or "")
            for card in (deck.get("cards") or [])
            if isinstance(card, dict) and card.get("name")
        }
        games = max(0, int(deck.get("games_count") or 0))
        wins = max(0, int(deck.get("wins") or 0))
        for name in names:
            appearances[name]["meta_deck_count"] += 1
            appearances[name]["observed_games"] += games
            appearances[name]["wins"] += wins

    owned_by_name = {str(card.get("name") or ""): card for card in collection.get("cards") or []}
    rows: list[dict[str, Any]] = []
    for name in active_deck:
        card = owned_by_name.get(name)
        stats = appearances.get(name)
        if not card or not stats:
            continue
        level = card.get("level")
        max_level = card.get("max_level")
        if level is None or max_level is None:
            continue
        capped_target = min(target_level, int(max_level))
        deficit = max(0, capped_target - int(level))
        if deficit <= 0:
            continue
        games = stats["observed_games"]
        win_rate = round(stats["wins"] / games * 100, 1) if games else None
        rows.append({
            "name": name,
            "name_ru": card.get("name_ru") or name,
            "icon": card.get("icon") or card.get("icon_base") or "",
            "level": int(level),
            "recommended_level": capped_target,
            "deficit": deficit,
            "meta_deck_count": stats["meta_deck_count"],
            "observed_games": games,
            "meta_win_rate": win_rate,
        })

    # More appearances in the strongest persisted decks is the primary signal;
    # sample size and win rate only break ties between equally common cards.
    rows.sort(
        key=lambda card: (
            -int(card["meta_deck_count"]),
            -int(card["observed_games"]),
            -(float(card["meta_win_rate"]) if card["meta_win_rate"] is not None else -1.0),
            -int(card["deficit"]),
            str(card["name"]),
        )
    )
    if not rows:
        return {
            **base,
            "status": "no_matching_cards",
            "message": "В текущей мета-выборке нет карт твоей колоды, которые ниже целевого уровня арены.",
        }
    return {**base, "status": "ok", "message": None, "cards": rows[:5]}
