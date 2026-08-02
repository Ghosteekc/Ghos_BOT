"""Публичный API Ghosteek AI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from bot.models.database import User
from bot.services.ghosteek_ai.composer import compose_answer
from bot.services.ghosteek_ai.intents import detect_intent
from bot.services.ghosteek_ai.router import route_intent
from bot.services.ghosteek_ai.session_context import (
    get_or_create_session,
    merge_request_context,
    update_session_from_payload,
)


@dataclass
class GhosteekAiAction:
    type: str
    path: str


@dataclass
class GhosteekAiResponse:
    intent: str
    answer: str
    sources: dict[str, Any] = field(default_factory=dict)
    actions: list[GhosteekAiAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "answer": self.answer,
            "sources": self.sources,
            "actions": [asdict(a) for a in self.actions],
        }


async def ask_ghosteek_ai(
    message: str,
    user: User,
    *,
    context: dict[str, Any] | None = None,
) -> GhosteekAiResponse:
    session = get_or_create_session(user.telegram_id)
    ctx = merge_request_context(session, context)

    context_cards: list[str] = []
    if isinstance(ctx.get("cards"), list):
        context_cards = [c for c in ctx["cards"] if isinstance(c, str)]

    detected = detect_intent(message, context_cards=context_cards)

    # Follow-up: «а что заменить?» без карт в тексте — берём колоду из сессии
    if detected.intent in {"improve_deck", "analyze_deck", "matchup", "game_coach"}:
        if len(detected.cards) < 8 and len(session.last_deck) >= 8:
            detected.cards = list(session.last_deck)
        if detected.intent == "matchup" and len(detected.opponent_cards) < 8:
            if len(session.last_opponent_deck) >= 8:
                detected.opponent_cards = list(session.last_opponent_deck)

    # Follow-up по тому же бою
    if detected.intent == "last_battle" and session.last_battle_index is not None:
        low = (message or "").lower()
        if any(k in low for k in ("этот бой", "тот бой", "ещё раз", "подробнее", "а что с боем")):
            ctx["battle_index"] = session.last_battle_index

    payload = await route_intent(detected, user, context=ctx)
    intent = str(payload.get("intent") or detected.intent)
    service = payload.get("service") or detected.service

    update_session_from_payload(
        session,
        intent=intent,
        service=str(service) if service else None,
        payload=payload,
    )

    answer = compose_answer(payload)
    actions = [
        GhosteekAiAction(type=a.get("type", "navigate"), path=a.get("path", "/"))
        for a in (payload.get("actions") or [])
        if isinstance(a, dict) and a.get("path")
    ]
    sources = {
        "intent": intent,
        "service": service,
        "ok": payload.get("ok"),
        "data": payload.get("data") or {},
        "persona": "coach",
        "session": session.to_public(),
    }
    return GhosteekAiResponse(
        intent=intent,
        answer=answer,
        sources=sources,
        actions=actions,
    )
