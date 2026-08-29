"""Shared prompt + JSON parsing for replay vision adapters."""

from __future__ import annotations

import json
import re
from typing import Any

# Compact prompt — fewer text tokens; vision image cost is fixed ~2048 on Groq.
VISION_SYSTEM_PROMPT = """Clash Royale replay frame analyzer.
Return ONLY JSON: {"observations":[{"event_type":"troop_visible","card_name":null,"side":"player","lane":"right","confidence":0.86}]}
event_type: card_visible|card_play_candidate|troop_visible|spell_visible|building_visible|tower_damage_candidate|defensive_interaction_candidate|offensive_interaction_candidate|unknown
card_name only if clearly visible in frame, else null. No thinking, no coaching."""

_THINKING_BLOCK_RE = re.compile(
    r"<think>.*?</think>",
    re.DOTALL | re.IGNORECASE,
)


def strip_model_thinking(text: str) -> str:
    """Drop Qwen/Groq reasoning wrappers so JSON extraction can run."""
    raw = text or ""
    cleaned = _THINKING_BLOCK_RE.sub("", raw)
    brace = cleaned.find("{")
    if brace >= 0:
        return cleaned[brace:].strip()
    if "<think>" in raw.lower():
        return ""
    return cleaned.strip()


def parse_vision_json_content(text: str) -> dict[str, Any] | list[Any] | None:
    raw = strip_model_thinking(text)
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
