"""Готовые советы тренера по архетипам — без генерации каждый раз."""

from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Any

_TIPS_PATH = Path(__file__).resolve().parents[2] / "data" / "coach_tips.json"

# Нормализация ключей архетипов → ключи JSON
_ARCH_ALIASES: dict[str, str] = {
    "beatdown": "Beatdown",
    "giant beatdown": "Giant Beatdown",
    "giant": "Giant Beatdown",
    "гигант": "Giant Beatdown",
    "cycle": "Cycle",
    "hog cycle": "Hog Cycle",
    "hog": "Hog Cycle",
    "хог": "Hog Cycle",
    "log bait": "Log Bait",
    "bait": "Log Bait",
    "bridge spam": "Bridge Spam",
    "bridgespam": "Bridge Spam",
    "control": "Control",
    "siege": "Siege",
    "lava": "Lava",
    "lavaloon": "Lava",
    "graveyard": "Graveyard",
    "gy": "Graveyard",
    "royal giant": "Royal Giant",
    "rg": "Royal Giant",
    "meta": "Meta",
}


@lru_cache(maxsize=1)
def _load_tips() -> dict[str, list[str]]:
    try:
        raw = json.loads(_TIPS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"default": ["Не оверкоммить без причины."]}
    out: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for key, val in raw.items():
            if isinstance(val, list):
                tips = [str(x).strip() for x in val if str(x).strip()]
                if tips:
                    out[str(key)] = tips
    if "default" not in out:
        out["default"] = ["Не оверкоммить без причины."]
    return out


def normalize_archetype(archetype: str | None) -> str:
    if not archetype:
        return "default"
    key = str(archetype).strip()
    low = key.lower()
    if key in _load_tips():
        return key
    if low in _ARCH_ALIASES:
        return _ARCH_ALIASES[low]
    for alias, canon in _ARCH_ALIASES.items():
        if alias in low:
            return canon
    return "default"


def pick_tip(archetype: str | None = None, *, seed: Any = None) -> str:
    """Выбрать готовый совет для архетипа (детерминированно при seed)."""
    tips_map = _load_tips()
    key = normalize_archetype(archetype)
    tips = tips_map.get(key) or tips_map["default"]
    if not tips:
        return "Не оверкоммить без причины."
    if seed is None:
        return random.choice(tips)
    idx = abs(hash(str(seed))) % len(tips)
    return tips[idx]


def list_archetypes() -> list[str]:
    return sorted(k for k in _load_tips().keys() if k != "default")
