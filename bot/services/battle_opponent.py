"""Resolve opponent display name and tag from Clash Royale battle payloads."""

from bot.services.clash_api import normalize_tag


def resolve_opponent_fields(opponent: dict | None) -> tuple[str, str]:
    if not opponent:
        return "Соперник", ""

    tag = normalize_tag(opponent.get("tag") or "")
    raw_name = (opponent.get("name") or "").strip()
    if raw_name in ("", "?", "Unknown", "unknown"):
        raw_name = ""

    if raw_name:
        return raw_name, tag

    if tag:
        return tag, tag

    return "Соперник", ""
