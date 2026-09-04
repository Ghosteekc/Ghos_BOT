"""Ingest trophy-road observations from persisted Ghosteek user battles."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.database import BattleCache
from bot.services.battle_time import normalize_battle_time
from bot.services.card_icons import deck_card_info_from_parsed, parse_deck_cards_json
from bot.services.clash_api import normalize_tag
from bot.services.meta_stats import (
    MODE_TROPHIES,
    cards_csv,
    deck_hash_from_names,
    observation_dedupe_key,
)

logger = logging.getLogger(__name__)


def _cards_from_cache_row(row: BattleCache) -> list[dict[str, Any]] | None:
    raw_json = (row.user_deck_json or "").strip()
    if raw_json:
        parsed = parse_deck_cards_json(raw_json)
        if len(parsed) == 8:
            return parsed

    names = [part.strip() for part in (row.user_deck or "").split(",") if part.strip()]
    if len(names) != 8:
        return None
    return [{"name": name} for name in names]


def observation_from_battle_cache_row(row: BattleCache) -> dict[str, Any] | None:
    """Verified Trophy Road battle cached from a linked Ghosteek user.

    ``BattleCache`` does not retain the original game-mode name.  A non-zero
    trophy delta is therefore the only reliable mode signal available here;
    accepting zero/missing values would mix cached, ranked, and casual rows
    into Trophy Road statistics.
    """
    try:
        trophy_change = int(row.trophy_change) if row.trophy_change is not None else 0
    except (TypeError, ValueError):
        return None
    if trophy_change == 0:
        return None

    player_tag = normalize_tag(row.player_tag)
    battle_time = normalize_battle_time(row.battle_time)
    if not player_tag or not battle_time:
        return None

    parsed = _cards_from_cache_row(row)
    if not parsed or len(parsed) != 8:
        return None

    names = [card["name"] for card in parsed if card.get("name")]
    deck_hash = deck_hash_from_names(names)
    if not deck_hash:
        return None

    infos = [
        deck_card_info_from_parsed(card if isinstance(card, dict) else {"name": str(card)}, slot=slot)
        for slot, card in enumerate(parsed)
    ]
    result = (row.result or "").strip().lower()
    if result not in {"win", "loss", "draw"}:
        result = "draw"

    return {
        "dedupe_key": observation_dedupe_key(player_tag, battle_time, MODE_TROPHIES),
        "player_tag": player_tag,
        "opponent_tag": (row.opponent_tag or "").strip(),
        "battle_time": battle_time,
        "mode": MODE_TROPHIES,
        "trophy_count": None,
        "deck_hash": deck_hash,
        "cards_csv": cards_csv(names),
        "cards_json": json.dumps(infos, ensure_ascii=False),
        "result": result,
        "source": "ghosteek_cache",
    }


async def ingest_trophies_from_battle_cache(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(BattleCache).where(BattleCache.trophy_change.is_not(None))
        )
    ).scalars().all()

    observations: list[dict[str, Any]] = []
    for row in rows:
        payload = observation_from_battle_cache_row(row)
        if payload is not None:
            observations.append(payload)

    logger.info(
        "Meta trophies cache ingest: %d ladder rows -> %d observations",
        len(rows),
        len(observations),
    )
    return observations
