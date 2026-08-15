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
    ReplayAmbiguousCardResponse,
    ReplayAnalyzeSuccess,
    ReplayBattleTimelineResponse,
    ReplayConfirmedCardResponse,
    ReplayDetectionResponse,
    ReplayEventResponse,
    ReplayFactsResponse,
    ReplayTacticalAnalysisResponse,
    ReplayTimelineItemResponse,
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
        if body.context.replay is not None:
            context["replay"] = body.context.replay.model_dump()

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
    "REPLAY_COMPRESS_FAILED": 400,
}


@router.post("/replay/analyze", response_model=None)
async def analyze_replay(
    user: User = Depends(require_subscription),
    file: UploadFile = File(...),
):
    """Validate video, sample frames, heuristic CR detection. No Qwen."""
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
    if detection.status in {"cr_replay", "uncertain", "not_cr_replay"}:
        session = ConversationManager.get_or_create(user.telegram_id)
        ConversationManager.set_last_replay(
            session,
            {
                "status": detection.status,
                "filename": outcome.filename,
                "duration_seconds": outcome.duration_seconds,
                "width": outcome.width,
                "height": outcome.height,
                "confidence": detection.confidence,
                **(
                    {
                        "has_analysis": True,
                        "coach_reply": outcome.analysis.coach_reply,
                        "coach_source": outcome.analysis.coach_source,
                    }
                    if outcome.analysis is not None and detection.status == "cr_replay"
                    else {}
                ),
            },
        )
        ConversationManager.save(user.telegram_id, session)
    replay_facts = None
    if outcome.analysis is not None and detection.status == "cr_replay":
        payload = outcome.analysis.to_dict()
        replay_facts = ReplayFactsResponse(
            source=str(payload.get("source") or "replay_analysis"),
            replay_status=str(payload.get("replay_status") or detection.status),
            confidence=float(payload.get("confidence") or detection.confidence),
            duration_seconds=float(payload.get("duration_seconds") or outcome.duration_seconds),
            frames_analyzed=int(payload.get("frames_analyzed") or detection.frames_analyzed),
            timeline=[
                ReplayTimelineItemResponse(**item)
                for item in (payload.get("timeline") or [])
                if isinstance(item, dict)
            ],
            facts=[str(x) for x in (payload.get("facts") or [])],
            limitations=[str(x) for x in (payload.get("limitations") or [])],
            confirmed_cards=[
                ReplayConfirmedCardResponse(**item)
                for item in (payload.get("confirmed_cards") or [])
                if isinstance(item, dict)
            ],
            ambiguous_cards=[
                ReplayAmbiguousCardResponse(**item)
                for item in (payload.get("ambiguous_cards") or [])
                if isinstance(item, dict)
            ],
            events=[
                ReplayEventResponse(**item)
                for item in (payload.get("events") or [])
                if isinstance(item, dict)
            ],
            confirmed_events=[
                ReplayEventResponse(**item)
                for item in (payload.get("confirmed_events") or [])
                if isinstance(item, dict)
            ],
            battle_timeline=(
                ReplayBattleTimelineResponse.model_validate(payload["battle_timeline"])
                if isinstance(payload.get("battle_timeline"), dict)
                else None
            ),
            tactical_analysis=(
                ReplayTacticalAnalysisResponse.model_validate(payload["tactical_analysis"])
                if isinstance(payload.get("tactical_analysis"), dict)
                else None
            ),
            coach_reply=(
                str(payload["coach_reply"])
                if payload.get("coach_reply") is not None
                else None
            ),
            coach_source=(
                str(payload["coach_source"])
                if payload.get("coach_source") is not None
                else None
            ),
        )
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
        replay_facts=replay_facts,
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
