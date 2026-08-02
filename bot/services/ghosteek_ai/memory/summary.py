"""Автоматическое сжатие истории → Conversation Summary.

Сейчас rule-based (без LLM). TODO(Qwen): суммаризировать через модель.
"""

from __future__ import annotations

import time
from typing import Iterable

from bot.services.ghosteek_ai.conversation.state import (
    MAX_SUMMARY_CHARS,
    ConversationState,
)
from bot.services.ghosteek_ai.models import ConversationMessage

# Когда interleaved сообщений ≥ порога — сжимаем старые в summary
COMPRESS_AT = 16
# Сколько последних сообщений оставляем в сыром виде после сжатия
KEEP_RECENT = 8


def _truncate(text: str, limit: int = 72) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


def _intent_label(intent: str | None) -> str:
    if not intent:
        return ""
    labels = {
        "analyze_deck": "разбор колоды",
        "improve_deck": "улучшение колоды",
        "build_deck": "сборка колоды",
        "last_battle": "разбор боя",
        "matchup": "матчап",
        "explain_mechanic": "механика",
        "card_info": "карта",
        "game_coach": "советы",
        "clarify": "уточнение",
        "unsupported": "отказ",
    }
    return labels.get(intent, intent)


def summarize_messages(
    messages: Iterable[ConversationMessage],
    *,
    state: ConversationState,
) -> str:
    """Сжать пачку сообщений в короткий текст summary."""
    msgs = list(messages)
    if not msgs:
        return ""

    topics: list[str] = []
    bullets: list[str] = []
    for m in msgs:
        if m.role == "user":
            label = _intent_label(m.intent)
            q = _truncate(m.content, 64)
            bullets.append(f"Игрок спросил «{q}»" + (f" ({label})" if label else ""))
            if label and label not in topics:
                topics.append(label)
        else:
            bullets.append(f"Ответ: {_truncate(m.content, 64)}")

    parts: list[str] = []
    if topics:
        parts.append("Темы: " + ", ".join(topics) + ".")
    if state.last_deck:
        parts.append("Колода: " + ", ".join(state.last_deck[:8]) + ".")
    if state.last_battle:
        won = state.last_battle.get("won")
        opp = state.last_battle.get("opponent_name") or "соперник"
        if won is True:
            parts.append(f"Бой: победа vs {opp}.")
        elif won is False:
            parts.append(f"Бой: поражение vs {opp}.")
    if state.last_tools:
        parts.append("Tools: " + ", ".join(state.last_tools[-5:]) + ".")
    if bullets:
        parts.append("История: " + " → ".join(bullets[:10]) + ".")

    return " ".join(parts).strip()


def merge_summary(existing: str, chunk: str) -> str:
    existing = (existing or "").strip()
    chunk = (chunk or "").strip()
    if not chunk:
        return existing[:MAX_SUMMARY_CHARS]
    if not existing:
        return chunk[:MAX_SUMMARY_CHARS]
    merged = f"{existing} || {chunk}"
    if len(merged) <= MAX_SUMMARY_CHARS:
        return merged
    # Оставляем хвост (более свежий контекст)
    return merged[-MAX_SUMMARY_CHARS:]


def maybe_compress(state: ConversationState) -> bool:
    """Если сообщений много — свернуть старые в summary.

    Returns:
        True если сжатие выполнено.
    """
    if len(state.messages) < COMPRESS_AT:
        return False

    keep = KEEP_RECENT
    if keep >= len(state.messages):
        return False

    old = state.messages[:-keep]
    recent = state.messages[-keep:]
    chunk = summarize_messages(old, state=state)
    state.summary = merge_summary(state.summary, chunk)
    state.summary_updated_at = time.time()
    state.messages = recent
    state.touch()
    return True
