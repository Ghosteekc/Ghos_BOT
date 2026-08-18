"""Clan-war decks from a verified snapshot — never from Ghosteek battle stats.

The snapshot is a local JSON file with source + updated_at. Runtime does not
scrape. If the file is missing, empty, or has no source, the API returns an
empty/unavailable state instead of inventing decks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "clan_war_decks.json"


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
