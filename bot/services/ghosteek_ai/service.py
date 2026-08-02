"""Публичный API Ghosteek AI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from bot.models.database import User
from bot.services.ghosteek_ai.composer import compose_answer
from bot.services.ghosteek_ai.intents import detect_intent
from bot.services.ghosteek_ai.router import route_intent


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
    ctx = context or {}
    context_cards = []
    if isinstance(ctx.get("cards"), list):
        context_cards = [c for c in ctx["cards"] if isinstance(c, str)]

    detected = detect_intent(message, context_cards=context_cards)
    payload = await route_intent(detected, user, context=ctx)
    answer = compose_answer(payload)
    actions = [
        GhosteekAiAction(type=a.get("type", "navigate"), path=a.get("path", "/"))
        for a in (payload.get("actions") or [])
        if isinstance(a, dict) and a.get("path")
    ]
    sources = {
        "intent": payload.get("intent"),
        "service": payload.get("service") or detected.service,
        "ok": payload.get("ok"),
        "data": payload.get("data") or {},
        "persona": "coach",
    }
    return GhosteekAiResponse(
        intent=str(payload.get("intent") or detected.intent),
        answer=answer,
        sources=sources,
        actions=actions,
    )
