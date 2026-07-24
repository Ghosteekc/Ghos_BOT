"""In-memory battle list cache per Telegram user (avoids duplicate CR API calls)."""

import time

from bot.services.clash_api import normalize_tag

BATTLE_TTL_SECONDS = 300  # 5 min — refresh from CR API at most once per 5 minutes

_battles_by_user: dict[int, list] = {}
_fetched_at_by_tag: dict[str, float] = {}


def get_session_battles(telegram_id: int) -> list | None:
    return _battles_by_user.get(telegram_id)


def set_session_battles(telegram_id: int, player_tag: str, battles: list) -> None:
    tag = normalize_tag(player_tag)
    _battles_by_user[telegram_id] = battles
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
