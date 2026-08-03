"""Общие хелперы переписывания предложений для validators."""

from __future__ import annotations

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n{2,}")


def split_units(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = _SENTENCE_SPLIT_RE.split(raw)
    return [p.strip() for p in parts if p and p.strip()]


def join_units(units: list[str]) -> str:
    cleaned = [u.strip() for u in units if u and u.strip()]
    if not cleaned:
        return ""
    # Абзацы сохраняем через \n\n только если исходник так намекал — здесь просто предложения.
    out: list[str] = []
    for u in cleaned:
        if u[-1] not in ".!?…":
            u = u + "."
        out.append(u)
    return " ".join(out)


def map_units(text: str, fn) -> str:
    units = split_units(text)
    if not units:
        return (text or "").strip()
    return join_units([fn(u) for u in units])
