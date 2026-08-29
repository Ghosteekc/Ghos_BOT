"""Shared prompt + JSON parsing for replay vision adapters."""

from __future__ import annotations

import json
from typing import Any

VISION_SYSTEM_PROMPT = """You analyze Clash Royale replay still frames.
Return ONLY valid JSON with this shape:
{"observations":[{"event_type":"troop_visible","card_name":null,"side":"player","lane":"right","confidence":0.86}]}

Rules:
- observation only — never coaching or advice
- event_type must be one of: card_visible, card_play_candidate, troop_visible, spell_visible, building_visible, tower_damage_candidate, defensive_interaction_candidate, offensive_interaction_candidate, unknown
- confidence is required (0.0-1.0)
- card_name must be null unless you clearly read the card text/icon from THIS frame
- never guess card names from deck patterns or gameplay context
- side: player, opponent, or unknown
- lane: left, right, center, or unknown
- if unsure, use unknown event_type and lower confidence
"""


def parse_vision_json_content(text: str) -> dict[str, Any] | list[Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def image_mime_for_path(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return "image/jpeg"
