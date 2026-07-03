"""Popular decks for the player's trophy bracket and arena."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from bot.services.card_data import get_card_elixir
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded, get_card_info
from bot.services.clash_api import normalize_tag
from bot.services.counter_engine import _get_arena_pool
from bot.services.deck_analyzer import analyze_deck, extract_deck
from bot.services.meta_analyzer import _guess_deck_name, _guess_category
from bot.services.meta_decks import META_DECKS

_ARENA_NAMES = {
    0: "Тренировочный лагерь",
    1: "Гоблинская арена",
    2: "Арена песков",
    3: "Драконья арена",
    4: "Нижняя пик",
    5: "Арена рабочих",
    6: "Сахарная фотография",
    7: "Скальная арена",
    8: "Арена изобилия",
    9: "Высший пик",
    10: "Арена электричества",
    11: "Электро-арена",
    12: "Механическая арена",
    13: "Запретная арена",
    14: "Трофейная арена",
    15: "Легендарная арена",
}


def arena_display_name(arena_id: int | None) -> str:
    if arena_id is None:
        return "Ваша лига"
    return _ARENA_NAMES.get(arena_id, f"Арена {arena_id}")


def _cards_to_infos(cards: list[str]) -> tuple[list[dict], float]:
    card_infos: list[dict] = []
    elixirs: list[float] = []
    for slot, name in enumerate(cards):
        info = get_card_info(name) or {}
        cost = float(info.get("elixir") or get_card_elixir(name))
        elixirs.append(cost)
        card_infos.append({
            "id": f"{name.lower().replace(' ', '-')}-{slot}",
            "name": name,
            "icon": info.get("icon") or "",
            "cost": int(cost),
            "evolution_level": 0,
            "is_hero": False,
            "slot": slot,
        })
    avg = round(sum(elixirs) / len(elixirs), 1) if elixirs else 0.0
    return card_infos, avg


def _meta_entry(meta, entry_id: int, description: str) -> dict:
    cards = list(meta.cards)
    card_infos, avg = _cards_to_infos(cards)
    return {
        "id": entry_id,
        "name": meta.name,
        "cards": card_infos,
        "winrate": 0.0,
        "total_games": 0,
        "avg_elixir": avg,
        "type": "arena",
        "category": meta.category,
        "deck_link": build_deck_share_link(cards),
        "description": description,
    }


async def get_arena_popular_decks(
    battles: list,
    player_tag: str,
    trophies: int,
    arena_id: int | None,
) -> dict:
    await ensure_cards_loaded()
    tag_norm = normalize_tag(player_tag)
    deck_stats: dict[str, dict] = defaultdict(
        lambda: {"wins": 0, "total": 0, "cards": []},
    )

    trophy_window = 400 if trophies >= 5000 else 300 if trophies >= 3000 else 250

    for battle in battles:
        btype = (battle.get("type") or "").lower()
        if btype in ("friendly", "clanmate", "warday", "boatbattle", "challenge"):
            continue
        team = battle.get("team", [{}])[0]
        if team.get("tag") and normalize_tag(team.get("tag", "")) != tag_norm:
            continue
        opponent = battle.get("opponent", [{}])[0]
        opp_trophies = int(opponent.get("startingTrophies") or 0)
        if trophies > 0 and opp_trophies > 0 and abs(opp_trophies - trophies) > trophy_window:
            continue
        cards = extract_deck(opponent)
        if len(cards) != 8:
            continue
        key = "|".join(sorted(cards))
        bucket = deck_stats[key]
        bucket["total"] += 1
        bucket["cards"] = cards
        if team.get("crowns", 0) > opponent.get("crowns", 0):
            bucket["wins"] += 1

    ranked = sorted(deck_stats.values(), key=lambda x: x["total"], reverse=True)
    entries: list[dict] = []
    seen_keys: set[str] = set()

    for i, data in enumerate(ranked[:12]):
        if data["total"] < 2:
            continue
        cards = data["cards"]
        key = "|".join(sorted(cards))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        card_infos, avg = _cards_to_infos(cards)
        wr = round(data["wins"] / data["total"] * 100, 1) if data["total"] else 0.0
        entries.append({
            "id": 4000 + i,
            "name": _guess_deck_name(cards),
            "cards": card_infos,
            "winrate": wr,
            "total_games": data["total"],
            "avg_elixir": avg,
            "type": "arena",
            "category": _guess_category(cards),
            "deck_link": build_deck_share_link(cards),
            "description": f"Популярна на вашей арене: {data['total']} боёв · ВР {wr:.0f}%",
        })

    pool = _get_arena_pool(arena_id)
    curated_id = 5000
    for meta in META_DECKS:
        if len(entries) >= 10:
            break
        if not all(c in pool for c in meta.cards):
            continue
        key = "|".join(sorted(meta.cards))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        entries.append(_meta_entry(
            meta,
            curated_id,
            f"Классическая колода для вашей арены · {meta.description}",
        ))
        curated_id += 1

    source = "battles" if any(e["total_games"] > 0 for e in entries) else "curated"
    if source == "battles" and any(e["total_games"] == 0 for e in entries):
        source = "mixed"

    return {
        "arena_name": arena_display_name(arena_id),
        "arena_id": arena_id,
        "trophies": trophies,
        "decks": entries[:12],
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def build_classic_meta_entries() -> tuple[list[dict], str | None, str]:
    """Static classic meta decks only (no live ladder scan)."""
    await ensure_cards_loaded()
    entries: list[dict] = []
    for i, meta in enumerate(META_DECKS):
        cards = list(meta.cards)
        card_infos, avg = _cards_to_infos(cards)
        entries.append({
            "id": 1000 + i,
            "name": meta.name,
            "cards": card_infos,
            "winrate": 0.0,
            "total_games": 0,
            "avg_elixir": avg,
            "type": "meta",
            "category": meta.category,
            "deck_link": build_deck_share_link(cards),
            "description": meta.description,
        })
    updated = datetime.now(timezone.utc).isoformat()
    return entries, updated, "classic"
