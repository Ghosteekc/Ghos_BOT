"""Composer — совместимость: делегирует в Response Generator."""

from __future__ import annotations

from typing import Any

from bot.services.ghosteek_ai.generator.response import compose_answer_from_payload


def compose_answer(payload: dict[str, Any]) -> str:
    """Старый API: payload {intent, ok, data, error} → текст."""
    return compose_answer_from_payload(payload)
