"""Fact-based labels for Clash Royale battle-log modes."""

from __future__ import annotations

from bot.services.battle_day_stats import is_ranked_1v1


def _key(raw: object) -> str:
    return str(raw or "").strip().lower().replace(" ", "")


def _game_mode_key(battle: dict) -> str:
    raw = battle.get("gameMode")
    if isinstance(raw, dict):
        return _key(raw.get("name") or raw.get("id"))
    return _key(raw)


def battle_mode_label(battle: dict) -> str | None:
    """Russian display label derived solely from the battle-log type and mode.

    Ranked battles deliberately return ``None`` because their existing league
    badge is the authoritative, more specific label in the UI.
    """
    if is_ranked_1v1(battle):
        return None

    battle_type = _key(battle.get("type"))
    mode_key = _game_mode_key(battle)

    # Supercell's TeamVsTeam payload is the 2v2 mode; some logs use type=trail.
    if battle_type in {"twovstwo", "2v2"} or "2v2" in mode_key or mode_key == "teamvsteam":
        return "2 на 2"
    if battle_type in {"clanmate", "friendly"}:
        return "Дружеский"
    if battle_type in {"warday", "boatbattle"} or "clanwar" in mode_key:
        return "Клановая война"
    if battle_type == "tournament" or "tournament" in mode_key:
        return "Турнир"
    if battle_type == "challenge" or "challenge" in mode_key:
        return "Испытание"
    if mode_key == "ladder":
        return "Кубки"
    if "classic" in mode_key:
        return "Классика"
    if "draft" in mode_key:
        return "Драфт"
    if "triple" in mode_key:
        return "Тройной эликсир"
    if "double" in mode_key:
        return "Двойной эликсир"
    if "touchdown" in mode_key:
        return "Тачдаун"

    # The API did not identify this mode closely enough to translate it safely.
    return "Режим не указан"
