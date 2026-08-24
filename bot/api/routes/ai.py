"""Ghosteek AI — оркестратор поверх существующих сервисов."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

from bot.api.deps import require_pro_linked
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
    ReplayMomentShotResponse,
    ReplayTacticalAnalysisResponse,
    ReplayTimelineItemResponse,
    ReplayVisualMomentResponse,
)
from bot.models.database import User
from bot.services.ghosteek_ai import ask_ghosteek_ai
from bot.services.ghosteek_ai.conversation.manager import ConversationManager
from bot.services.ghosteek_ai.replay import ReplayError, get_replay_service
from bot.services.ghosteek_ai.replay.evidence import get_evidence_store
from bot.services.ghosteek_ai.session_context import clear_session
from fastapi.responses import Response

router = APIRouter(prefix="/api/ai", tags=["ai"])

require_ai_pro = require_pro_linked("ai_coach")


def _public_visual_moment(item: dict) -> dict:
    """Strip any accidental path keys before API serialization."""
    frame = item.get("evidence_frame") if isinstance(item.get("evidence_frame"), dict) else {}
    safe_frame: dict = {
        "timestamp_seconds": float(frame.get("timestamp_seconds") or item.get("timestamp_seconds") or 0),
        "frame_index": int(frame.get("frame_index") or 0),
    }
    if frame.get("width") is not None:
        safe_frame["width"] = int(frame["width"])
    if frame.get("height") is not None:
        safe_frame["height"] = int(frame["height"])
    return {
        "event_type": str(item.get("event_type") or "unknown"),
        "timestamp_seconds": float(item.get("timestamp_seconds") or 0),
        "card_name": item.get("card_name"),
        "confidence": float(item.get("confidence") or 0),
        "evidence_frame": safe_frame,
        "evidence_id": item.get("evidence_id"),
        "clip_id": item.get("clip_id"),
        "clip_available": bool(item.get("clip_available")),
        "preview_base64": item.get("preview_base64"),
        "source": str(item.get("source") or "vision"),
        "title": item.get("title"),
        "short_description": item.get("short_description"),
        "explanation_kind": item.get("explanation_kind"),
        "explanation_source": item.get("explanation_source"),
    }


@router.post("/ask", response_model=GhosteekAiAskResponse)
async def ask_ai(
    body: GhosteekAiAskRequest,
    user: User = Depends(require_ai_pro),
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
    user: User = Depends(require_ai_pro),
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
            candidate_events=[
                ReplayEventResponse(**item)
                for item in (payload.get("candidate_events") or [])
                if isinstance(item, dict)
            ],
            moment_shots=[
                ReplayMomentShotResponse(**item)
                for item in (payload.get("moment_shots") or [])
                if isinstance(item, dict) and item.get("image_base64")
            ],
            visual_moments=[
                ReplayVisualMomentResponse.model_validate(_public_visual_moment(item))
                for item in (payload.get("visual_moments") or [])
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
            grounded_summary=(
                str(payload["grounded_summary"])
                if payload.get("grounded_summary") is not None
                else None
            ),
            grounded_limitations=(
                str(payload["grounded_limitations"])
                if payload.get("grounded_limitations") is not None
                else None
            ),
            grounded_summary_source=(
                str(payload["grounded_summary_source"])
                if payload.get("grounded_summary_source") is not None
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


@router.get("/replay/evidence/{evidence_id}")
async def get_replay_evidence(
    evidence_id: str,
    user: User = Depends(require_ai_pro),
):
    """Serve opaque evidence bytes. Never accepts filesystem paths."""
    del user  # auth gate only
    stored = get_evidence_store().get(evidence_id)
    if stored is None:
        return JSONResponse(status_code=404, content={"ok": False, "error_code": "EVIDENCE_NOT_FOUND"})
    data, content_type = stored
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/session")
async def get_ai_session(user: User = Depends(require_ai_pro)) -> dict:
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
async def clear_ai_session(user: User = Depends(require_ai_pro)) -> dict:
    """Очистить Session Context текущего пользователя (кнопка «Начать новый разговор»)."""
    clear_session(user.telegram_id)
    return {"ok": True, "cleared": True}
