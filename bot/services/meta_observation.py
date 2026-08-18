"""Parse one battlelog row into a meta observation payload."""

from __future__ import annotations

import json
from typing import Any

from bot.services.battle_time import battle_time_from_record
from bot.services.card_icons import cards_from_team, deck_card_info_from_parsed, normalize_deck_upgrades
from bot.services.clash_api import normalize_tag
from bot.services.meta_stats import (
    MODE_TROPHIES,
    battle_result,
    cards_csv,
    classify_battle_mode,
    deck_hash_from_names,
    observation_dedupe_key,
)


def observation_from_battle(player_tag: str, battle: dict, *, trophy_min: int) -> dict[str, Any] | None:
    mode = classify_battle_mode(battle)
    if mode is None:
        return None
    battle_time = battle_time_from_record(battle)
    if not battle_time:
        return None

    tag_norm = normalize_tag(player_tag)
    team = battle.get("team", [{}])[0]
    team_tag = team.get("tag") or ""
    if team_tag and normalize_tag(team_tag) != tag_norm:
        return None

    trophies = int(team.get("startingTrophies") or 0)
    if mode == MODE_TROPHIES and trophies < trophy_min:
        return None

    parsed = cards_from_team(team)
    if len(parsed) != 8:
        return None
    parsed = normalize_deck_upgrades(parsed)
    names = [c["name"] for c in parsed]
    deck_hash = deck_hash_from_names(names)
    if not deck_hash:
        return None

    opponent = battle.get("opponent", [{}])[0]
    opp_tag = opponent.get("tag") or ""
    infos = [deck_card_info_from_parsed(c, slot=i) for i, c in enumerate(parsed)]
    return {
        "dedupe_key": observation_dedupe_key(tag_norm, battle_time, mode),
        "player_tag": tag_norm,
        "opponent_tag": normalize_tag(opp_tag) if opp_tag else "",
        "battle_time": battle_time,
        "mode": mode,
        "trophy_count": trophies or None,
        "deck_hash": deck_hash,
        "cards_csv": cards_csv(names),
        "cards_json": json.dumps(infos, ensure_ascii=False),
        "result": battle_result(team, opponent),
        "source": "cr_api",
    }
