"""Русская терминология тренера Clash Royale."""

from __future__ import annotations

import re

# Длинные фразы первыми
_TERM_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bGiant\s+Beatdown\b", re.I), "битдаун на Гиганте"),
    (re.compile(r"\bDark\s+Prince\b", re.I), "Тёмный принц"),
    (re.compile(r"\bRoyal\s+Giant\b", re.I), "Королевский гигант"),
    (re.compile(r"\bElite\s+Barbarians\b", re.I), "Элитные варвары"),
    (re.compile(r"\bLog\s+Bait\b", re.I), "лог-бейт"),
    (re.compile(r"\bBridge\s+Spam\b", re.I), "bridge spam"),
    (re.compile(r"\bHog\s+Cycle\b", re.I), "хог-цикл"),
    (re.compile(r"\bwin[\s-]?condition\b", re.I), "вин-кондишн"),
    (re.compile(r"\bcounter[\s-]?push\b", re.I), "контрпуш"),
    (re.compile(r"\bovercommit(?:ting|ted|s)?\b", re.I), "оверкоммит"),
    (re.compile(r"\bBeatdown\b", re.I), "битдаун"),
    (re.compile(r"\bControl\b"), "контроль"),
    (re.compile(r"\bSiege\b"), "осада"),
    (re.compile(r"\bCycle\b"), "цикл"),
    (re.compile(r"\bPrince\b"), "Принц"),
    (re.compile(r"\bGiant\b"), "Гигант"),
    (re.compile(r"\bP\.?E\.?K\.?K\.?A\.?\b", re.I), "П.Е.К.К.А"),
    (re.compile(r"\bPEKKA\b", re.I), "П.Е.К.К.А"),
]

_ARCHETYPE_LABELS: dict[str, str] = {
    "Beatdown": "битдаун",
    "Giant Beatdown": "битдаун на Гиганте",
    "Cycle": "цикл",
    "Hog Cycle": "хог-цикл",
    "Log Bait": "лог-бейт",
    "Bridge Spam": "bridge spam",
    "Control": "контроль",
    "Siege": "осада",
    "Lava": "лавалун",
    "Graveyard": "кладбище",
    "Royal Giant": "Королевский гигант",
    "Meta": "мета",
}


def archetype_label(archetype: str | None) -> str:
    if not archetype:
        return "эта сборка"
    raw = str(archetype).strip()
    return _ARCHETYPE_LABELS.get(raw) or _ARCHETYPE_LABELS.get(raw.title()) or raw


def apply_glossary(text: str) -> str:
    """Заменить англ. термины на русские аналоги, где они привычны игрокам."""
    out = text or ""
    for pattern, repl in _TERM_REPLACEMENTS:
        out = pattern.sub(repl, out)
    return out
