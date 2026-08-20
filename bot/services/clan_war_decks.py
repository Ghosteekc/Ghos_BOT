"""Clan-war deck snapshot built from Ghosteek battlelog sample (warday / boatbattle).

The snapshot is persisted as JSON with source + updated_at. If collection finds
nothing, the API returns an empty/unavailable state instead of inventing decks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.services.card_icons import cards_from_team, normalize_deck_upgrades
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient
from bot.services.deck_analyzer import analyze_deck
from bot.services.meta_stats import deck_hash_from_names

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "clan_war_decks.json"
CW_BATTLE_TYPES = frozenset({"warday", "boatbattle"})
SOURCE_LABEL = "Ghosteek · бои КВ в выборке"
FALLBACK_SOURCE_LABEL = "Ghosteek · базовые колоды для КВ"


def load_clan_war_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        return {
            "available": False,
            "source": "",
            "source_url": "",
            "updated_at": None,
            "decks": [],
            "message": "Готовые колоды КВ пока не загружены.",
        }
    try:
        raw = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Clan-war snapshot unreadable: %s", exc)
        return {
            "available": False,
            "source": "",
            "source_url": "",
            "updated_at": None,
            "decks": [],
            "message": "Источник колод КВ недоступен.",
        }

    source = str(raw.get("source") or "").strip()
    decks = raw.get("decks") if isinstance(raw.get("decks"), list) else []
    cleaned: list[dict[str, Any]] = []
    for item in decks:
        if not isinstance(item, dict):
            continue
        cards = [c for c in (item.get("cards") or []) if isinstance(c, str) and c.strip()]
        if len(cards) != 8:
            continue
        cleaned.append({
            "cards": cards,
            "name": str(item.get("name") or "").strip(),
            "role": str(item.get("role") or item.get("type") or "").strip(),
            "recommendation": str(item.get("recommendation") or item.get("note") or "").strip(),
        })

    available = bool(source) and bool(cleaned)
    return {
        "available": available,
        "source": source,
        "source_url": str(raw.get("source_url") or "").strip(),
        "updated_at": raw.get("updated_at"),
        "decks": cleaned if available else [],
        "message": None if available else (
            "Готовые колоды КВ пока не загружены."
            if not cleaned
            else "Источник колод КВ не указан."
        ),
    }


def _deck_names_from_cw_battle(battle: dict) -> list[str] | None:
    team = battle.get("team", [{}])[0]
    parsed = cards_from_team(team)
    if len(parsed) != 8:
        return None
    parsed = normalize_deck_upgrades(parsed)
    return [card["name"] for card in parsed]


def _guess_cw_role(names: list[str]) -> str:
    stats = analyze_deck(names)
    if stats.avg_elixir >= 4.1:
        return "Натиск"
    if stats.avg_elixir <= 3.3:
        return "Цикл"
    if stats.buildings:
        return "Контроль"
    return "Универсал"


def _guess_cw_name(names: list[str]) -> str:
    stats = analyze_deck(names)
    if stats.win_conditions:
        from bot.services.card_names_ru import card_name_ru

        wc = card_name_ru(stats.win_conditions[0], short=True)
        return wc
    return "Колода КВ"


def _curated_cw_decks() -> list[dict[str, Any]]:
    from bot.services.meta_decks import CATEGORY_LABELS, META_DECKS

    decks: list[dict[str, Any]] = []
    for meta in META_DECKS[:10]:
        cards = list(meta.cards)
        if len(cards) != 8:
            continue
        decks.append({
            "cards": cards,
            "name": meta.name,
            "role": CATEGORY_LABELS.get(meta.category, meta.category),
            "recommendation": meta.description or "Базовая колода для КВ",
        })
    return decks


def _write_snapshot(decks: list[dict[str, Any]], *, source: str = SOURCE_LABEL) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source,
        "source_url": "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "decks": decks,
    }
    SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def refresh_clan_war_snapshot(
    client: ClashRoyaleClient,
    players: list[dict[str, Any]],
    *,
    concurrency: int = 4,
    min_games: int = 2,
    limit: int = 12,
) -> dict[str, Any]:
    """Scan player battlelogs for clan-war battles and persist top decks."""
    counts: Counter[str] = Counter()
    deck_cards: dict[str, list[str]] = {}
    sem = asyncio.Semaphore(max(1, concurrency))
    scanned = 0

    async def fetch_one(item: dict[str, Any]) -> None:
        nonlocal scanned
        tag = item.get("tag") or ""
        if not tag:
            return
        async with sem:
            try:
                battles = await client.get_battlelog(tag)
            except ClashRoyaleAPIError as exc:
                if exc.status == 429:
                    raise
                logger.debug("Clan-war battlelog skip %s: %s", tag, exc)
                return
        scanned += 1
        for battle in battles:
            btype = str(battle.get("type") or "").lower().replace(" ", "")
            if btype not in CW_BATTLE_TYPES:
                continue
            names = _deck_names_from_cw_battle(battle)
            if not names:
                continue
            deck_hash = deck_hash_from_names(names)
            if not deck_hash:
                continue
            counts[deck_hash] += 1
            deck_cards[deck_hash] = names

    await asyncio.gather(*[fetch_one(player) for player in players], return_exceptions=False)

    ranked_hashes = [deck_hash for deck_hash, games in counts.most_common(limit) if games >= min_games]
    decks: list[dict[str, Any]] = []
    for deck_hash in ranked_hashes:
        names = deck_cards[deck_hash]
        games = counts[deck_hash]
        decks.append({
            "cards": names,
            "name": _guess_cw_name(names),
            "role": _guess_cw_role(names),
            "recommendation": f"{games} боёв в выборке Ghosteek",
        })

    if decks:
        _write_snapshot(decks)
        logger.info("Clan-war snapshot updated: %d decks from %d players", len(decks), scanned)
    else:
        curated = _curated_cw_decks()
        if curated:
            _write_snapshot(curated, source=FALLBACK_SOURCE_LABEL)
            logger.info(
                "Clan-war snapshot filled with %d curated decks (no CW battles in %d logs)",
                len(curated),
                scanned,
            )
        else:
            logger.info("Clan-war snapshot unchanged: no CW battles in %d player logs", scanned)

    return load_clan_war_snapshot()
