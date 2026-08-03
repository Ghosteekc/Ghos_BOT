"""Публичный API Ghosteek AI — AI Orchestrator pipeline."""

from __future__ import annotations

from typing import Any

from bot.models.database import User
from bot.services.ghosteek_ai.context.builder import ContextBuilder
from bot.services.ghosteek_ai.conversation.manager import ConversationManager
from bot.services.ghosteek_ai.generator.factory import get_response_generator
from bot.services.ghosteek_ai.intents import detect_intent
from bot.services.ghosteek_ai.models import GhosteekAiAction, GhosteekAiResponse
from bot.services.ghosteek_ai.planner.planner import Planner
from bot.services.ghosteek_ai.safety.layer import SafetyLayer
from bot.services.ghosteek_ai.tools.base import ToolCaller, get_default_registry

_REGISTRY = get_default_registry()
_CALLER = ToolCaller(_REGISTRY)
# Default generator — template. Qwen не подключен.
# HOOK: get_response_generator("qwen") после подключения модели.
_GENERATOR = get_response_generator("template")


async def ask_ghosteek_ai(
    message: str,
    user: User,
    *,
    context: dict[str, Any] | None = None,
) -> GhosteekAiResponse:
    """
    Orchestrator pipeline:

    Conversation Manager
      → Intent Detection
      → Planner
      → bootstrap AIContext
      → ToolCaller (tools ↔ AIContext)
      → Response Generator
      → Safety Layer
      → Response
    """
    session = ConversationManager.get_or_create(user.telegram_id)
    ConversationManager.add_user_message(session, message)

    req_ctx = ConversationManager.merge_request_context(session, context)

    context_cards: list[str] = []
    if isinstance(req_ctx.get("cards"), list):
        context_cards = [c for c in req_ctx["cards"] if isinstance(c, str)]

    detected = detect_intent(message, context_cards=context_cards)
    detected = ConversationManager.apply_followup_enrichment(
        session, detected, message, req_ctx
    )

    plan = Planner.plan(detected)
    tool_args = dict(plan.tools[0].args) if plan.tools else {}

    ai_context = ContextBuilder.bootstrap(
        user=user,
        plan=plan,
        conversation=session,
        request_context=req_ctx,
        raw_message=message,
        tool_args=tool_args,
    )

    tool_results = await _CALLER.execute_plan(plan, ai_context)
    tool_names = [tr.tool for tr in tool_results]

    # HOOK_RESPONSE_GENERATOR: заменить на get_response_generator("qwen") при подключении LLM
    raw_answer = _GENERATOR.generate(ai_context)
    answer = SafetyLayer.apply(raw_answer, ai_context)

    intent_name = ai_context.intent.request
    ConversationManager.update_from_ai_context(
        session,
        intent=intent_name,
        service=ai_context.intent.service,
        data=ai_context.data,
        ok=ai_context.ok,
        active_topic=intent_name,
        tools=tool_names,
    )
    ConversationManager.add_assistant_message(session, answer, intent=intent_name)
    ConversationManager.save(user.telegram_id, session)

    actions = [
        GhosteekAiAction(type=a.get("type", "navigate"), path=a.get("path", "/"))
        for a in ai_context.actions
        if isinstance(a, dict) and a.get("path")
    ]

    sources = {
        "intent": intent_name,
        "service": ai_context.intent.service,
        "ok": ai_context.ok,
        "data": ai_context.data or {},
        "persona": "coach",
        "constraints": True,
        "session": session.to_public(),
        "tools": tool_names,
        "error_code": ai_context.error_code,
        "memory": {
            "has_summary": bool(session.summary),
            "summary_preview": session.to_public().get("summary_preview", ""),
            "questions": list(session.last_questions[-5:]),
            "recent_count": len(session.messages),
        },
        "ai_context": {
            "player": ai_context.player.to_dict(),
            "arena": ai_context.arena.to_dict(),
            "has_deck": len(ai_context.deck.cards) >= 8,
            "has_battle": bool(ai_context.battle.raw or ai_context.battle.battle_index is not None),
            "has_summary": bool(ai_context.conversation.summary),
        },
    }

    return GhosteekAiResponse(
        intent=intent_name,
        answer=answer,
        sources=sources,
        actions=actions,
    )
