"""Honest follow-up when a CR replay was accepted but Stage 4 coaching is not ready."""

from __future__ import annotations

import re
from typing import Any

from bot.services.ghosteek_ai.voice import coach_reply

_REPLAY_COACHING_RE = re.compile(
    r"("
    r"ошибк|"
    r"что\s+не\s+так|"
    r"где\s+я\s+ошиб|"
    r"разбер|"
    r"анализ|"
    r"посмотр|"
    r"оцени|"
    r"в\s+этом\s+видео|"
    r"этом\s+видео|"
    r"этой\s+записи|"
    r"этот\s+репле|"
    r"этот\s+матч|"
    r"репле|"
    r"видео"
    r")",
    re.IGNORECASE,
)

_ACCEPTED = frozenset({"cr_replay", "uncertain"})


def is_replay_coaching_request(message: str) -> bool:
    return bool(_REPLAY_COACHING_RE.search(message or ""))


def normalize_replay_meta(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status") or "").strip()
    if status not in {"cr_replay", "not_cr_replay", "uncertain"}:
        return None
    filename = str(raw.get("filename") or "").strip() or "replay"
    try:
        duration = float(raw.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    try:
        width = int(raw.get("width") or 0)
        height = int(raw.get("height") or 0)
    except (TypeError, ValueError):
        width, height = 0, 0
    try:
        confidence = float(raw.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "status": status,
        "filename": filename[:180],
        "duration_seconds": round(max(0.0, duration), 3),
        "width": max(0, width),
        "height": max(0, height),
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "accepted": status in _ACCEPTED,
    }


def resolve_replay_meta(
    session_replay: Any,
    request_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    req = None
    if isinstance(request_context, dict):
        req = normalize_replay_meta(request_context.get("replay"))
    sess = normalize_replay_meta(session_replay)
    return req or sess


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    m, s = divmod(total, 60)
    return f"{m}:{s:02d}"


def reply_replay_pending_analysis(meta: dict[str, Any]) -> str:
    status = str(meta.get("status") or "")
    if status == "not_cr_replay":
        return coach_reply(
            "Это видео я уже проверял — на Clash Royale оно не похоже.",
            why="Без записи боя из игры разобрать ошибки по кадрам нельзя.",
            tip="Пришли реплей из Clash Royale или опиши момент текстом.",
            intent="replay_pending",
        )

    duration = format_duration(float(meta.get("duration_seconds") or 0))
    w = int(meta.get("width") or 0)
    h = int(meta.get("height") or 0)
    dims = f"{w}×{h}" if w > 0 and h > 0 else ""
    where = f"реплей {duration}" + (f", {dims}" if dims else "")
    if status == "uncertain":
        lead = f"Видео получил ({where}), но Clash Royale ещё не уверен."
    else:
        lead = f"Твой реплей Clash Royale вижу ({where})."

    return coach_reply(
        lead,
        why="Покадровый разбор ошибок ещё не подключен — сейчас только приём и проверка, что это CR.",
        tip="Опиши ключевой момент текстом или спроси про колоду/матчап — это уже умею.",
        intent="replay_pending",
    )
