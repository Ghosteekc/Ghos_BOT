"""Ghosteek AI — оркестратор поверх существующих сервисов."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from bot.api.deps import require_subscription
from bot.api.schemas import (
    GhosteekAiAction,
    GhosteekAiAskRequest,
    GhosteekAiAskResponse,
)
from bot.models.database import User
from bot.services.ghosteek_ai import ask_ghosteek_ai
from bot.services.ghosteek_ai.session_context import clear_session

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/ask", response_model=GhosteekAiAskResponse)
async def ask_ai(
    body: GhosteekAiAskRequest,
    user: User = Depends(require_subscription),
) -> GhosteekAiAskResponse:
    context: dict = {}
    if body.context is not None:
        if body.context.cards is not None:
            context["cards"] = body.context.cards
        if body.context.opponent_cards is not None:
            context["opponent_cards"] = body.context.opponent_cards
        if body.context.battle_index is not None:
            context["battle_index"] = body.context.battle_index
        if body.context.battle_time is not None:
            context["battle_time"] = body.context.battle_time

    result = await ask_ghosteek_ai(body.message, user, context=context or None)
    return GhosteekAiAskResponse(
        intent=result.intent,
        answer=result.answer,
        sources=result.sources,
        actions=[GhosteekAiAction(type=a.type, path=a.path) for a in result.actions],
    )


@router.delete("/session")
async def clear_ai_session(user: User = Depends(require_subscription)) -> dict:
    """Очистить Session Context текущего пользователя (конец сессии на /ai)."""
    clear_session(user.telegram_id)
    return {"ok": True, "cleared": True}
