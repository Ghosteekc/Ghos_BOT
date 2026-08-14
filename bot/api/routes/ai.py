"""Ghosteek AI — оркестратор поверх существующих сервисов."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

from bot.api.deps import require_subscription
from bot.api.schemas import (
    GhosteekAiAction,
    GhosteekAiAskRequest,
    GhosteekAiAskResponse,
    DeckCardResponse,
    ReplayAnalyzeSuccess,
    ReplayDetectionResponse,
)
from bot.models.database import User
from bot.services.ghosteek_ai import ask_ghosteek_ai
from bot.services.ghosteek_ai.conversation.manager import ConversationManager
from bot.services.ghosteek_ai.replay import ReplayError, get_replay_service
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
    deck_card = None
    if isinstance(result.deck_card, dict) and result.deck_card.get("deck"):
        deck_card = DeckCardResponse.model_validate(result.deck_card)
    return GhosteekAiAskResponse(
        intent=result.intent,
        answer=result.answer,
        sources=result.sources,
        actions=[GhosteekAiAction(type=a.type, path=a.path) for a in result.actions],
        deck_card=deck_card,
        battle_card=None,
        analysis_card=None,
    )


_REPLAY_HTTP_STATUS = {
    "REPLAY_BUSY": 409,
    "REPLAY_FFMPEG_UNAVAILABLE": 503,
    "REPLAY_INTERNAL_ERROR": 500,
    "REPLAY_FRAME_EXTRACTION_FAILED": 400,
    "REPLAY_FRAME_ANALYSIS_FAILED": 400,
    "REPLAY_ANALYSIS_TIMEOUT": 400,
}


@router.post("/replay/analyze", response_model=None)
async def analyze_replay(
    user: User = Depends(require_subscription),
    file: UploadFile = File(...),
):
    """Validate video, sample frames, heuristic CR detection. No Qwen."""
    del user
    service = get_replay_service()
    try:
        outcome = await service.analyze_upload(
            filename=file.filename,
            content_type=file.content_type,
            read=file.read,
        )
    except ReplayError as exc:
        status = _REPLAY_HTTP_STATUS.get(exc.code, 400)
        return JSONResponse(
            status_code=status,
            content={"ok": False, "error_code": exc.code},
        )
    finally:
        await file.close()
    detection = outcome.detection
    return ReplayAnalyzeSuccess(
        status=detection.status,
        filename=outcome.filename,
        mime_type=outcome.mime_type,
        size_bytes=outcome.size_bytes,
        duration_seconds=outcome.duration_seconds,
        width=outcome.width,
        height=outcome.height,
        fps=outcome.fps,
        replay_detection=ReplayDetectionResponse(
            status=detection.status,
            confidence=detection.confidence,
            frames_analyzed=detection.frames_analyzed,
            observations=list(detection.observations),
        ),
    )


@router.get("/session")
async def get_ai_session(user: User = Depends(require_subscription)) -> dict:
    """Read-only: история ConversationManager для UI-чата (без изменения состояния)."""
    session = ConversationManager.get(user.telegram_id)
    if session is None:
        return {"ok": True, "exists": False, "messages": [], "session": None}
    return {
        "ok": True,
        "exists": True,
        "messages": session.recent_messages_public(limit=40),
        "session": session.to_public(),
    }


@router.delete("/session")
async def clear_ai_session(user: User = Depends(require_subscription)) -> dict:
    """Очистить Session Context текущего пользователя (кнопка «Начать новый разговор»)."""
    clear_session(user.telegram_id)
    return {"ok": True, "cleared": True}
