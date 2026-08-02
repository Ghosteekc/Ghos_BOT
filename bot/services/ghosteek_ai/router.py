"""Router — compatibility shim для тестов (`patch router.*`).

Новый runtime-путь: Planner → Tools. Символы ниже — точки патча.
"""

from __future__ import annotations

from typing import Any

from bot.models.database import User
from bot.services.ghosteek_ai.intents import DetectedIntent
from bot.services.ghosteek_ai.tools.deps import (
    RecommendationEngine,
    calculate_deck_synergy,
    load_and_persist,
    resolve_player_deck,
)

# Имена, которые патчат тесты
_resolve_player_deck = resolve_player_deck

__all__ = [
    "RecommendationEngine",
    "calculate_deck_synergy",
    "load_and_persist",
    "_resolve_player_deck",
    "route_intent",
]


async def route_intent(
    detected: DetectedIntent,
    user: User,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Совместимость: Planner + Tools → payload shape."""
    from bot.services.ghosteek_ai.planner.planner import Planner
    from bot.services.ghosteek_ai.tools.base import build_default_registry, execute_plan

    plan = Planner.plan(detected)
    results = await execute_plan(
        plan,
        user=user,
        context=context or {},
        session_public={},
        raw_message=detected.raw,
        registry=build_default_registry(),
    )
    primary = results[0] if results else None
    if primary is None:
        return {
            "intent": plan.intent,
            "service": plan.service,
            "ok": False,
            "error": None,
            "data": {},
            "actions": [],
        }
    return {
        "intent": plan.intent,
        "service": plan.service,
        "ok": primary.ok,
        "error": primary.error_code,
        "data": primary.data,
        "actions": primary.actions,
        "error_code": primary.error_code,
        "error_params": primary.error_params,
    }
