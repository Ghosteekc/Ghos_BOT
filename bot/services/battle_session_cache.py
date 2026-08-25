"""In-memory battle list cache per Telegram user (avoids duplicate CR API calls).

Battles are always stored with the player_tag they belong to. After a re-link,
callers must pass the expected tag so a previous account's log is never reused.
"""

from __future__ import annotations

import time
from typing import TypedDict

from bot.services.clash_api import normalize_tag

BATTLE_TTL_SECONDS = 300  # 5 min — refresh from CR API at most once per 5 minutes


class _SessionEntry(TypedDict):
    tag: str
    battles: list


_battles_by_user: dict[int, _SessionEntry] = {}
_fetched_at_by_tag: dict[str, float] = {}


def get_session_battles(telegram_id: int, expected_tag: str | None = None) -> list | None:
    """Return cached battles for this Telegram user.

    If ``expected_tag`` is set, returns data only when it matches the stored tag.
    """
    entry = _battles_by_user.get(telegram_id)
    if entry is None:
        return None
    if expected_tag is not None:
        want = normalize_tag(expected_tag)
        if not want or entry["tag"] != want:
            return None
    return entry["battles"]


def get_session_tag(telegram_id: int) -> str | None:
    entry = _battles_by_user.get(telegram_id)
    return entry["tag"] if entry else None


def set_session_battles(telegram_id: int, player_tag: str, battles: list) -> None:
    tag = normalize_tag(player_tag)
    if not tag:
        return
    _battles_by_user[telegram_id] = {"tag": tag, "battles": battles}
    _fetched_at_by_tag[tag] = time.time()


def mark_tag_fetched(player_tag: str) -> None:
    _fetched_at_by_tag[normalize_tag(player_tag)] = time.time()


def is_fresh(player_tag: str) -> bool:
    ts = _fetched_at_by_tag.get(normalize_tag(player_tag), 0)
    return (time.time() - ts) < BATTLE_TTL_SECONDS


def clear_user(telegram_id: int, player_tag: str | None = None) -> None:
    _battles_by_user.pop(telegram_id, None)
    if player_tag:
        _fetched_at_by_tag.pop(normalize_tag(player_tag), None)
