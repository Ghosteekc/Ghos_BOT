"""Публичный API Ghosteek AI — LLM Tool Calling + Planner fallback."""

from __future__ import annotations

import logging
import time
from typing import Any

from bot.config import settings
from bot.models.database import User
from bot.services.ghosteek_ai.agent.runner import run_llm_agent
from bot.services.ghosteek_ai.context.builder import ContextBuilder
from bot.services.ghosteek_ai.conversation.manager import ConversationManager
from bot.services.ghosteek_ai.generator.factory import (
    get_response_generator,
    get_template_generator,
)
from bot.services.ghosteek_ai.intents import detect_intent
from bot.services.ghosteek_ai.llm.provider import LLMProvider, get_llm_provider
from bot.services.ghosteek_ai.models import GhosteekAiAction, GhosteekAiResponse, Plan
from bot.services.ghosteek_ai.planner.planner import Planner
from bot.services.ghosteek_ai.safety.layer import SafetyLayer
from bot.services.ghosteek_ai.tools.base import ToolCaller, get_default_registry

logger = logging.getLogger(__name__)

_REGISTRY = get_default_registry()
_CALLER = ToolCaller(_REGISTRY)
_TEMPLATE = get_template_generator()

MODE_AUTO = "auto"
MODE_AGENT = "agent"
MODE_PLANNER = "planner"


def _sanity_blocks_explain(ai_context) -> bool:
    """Если Deck Sanity не пройден — не даём LLM оправдывать колоду."""
    from bot.services.deck_sanity_validator import sanity_payload_from_data
    from bot.services.ghosteek_ai.intents import (
        INTENT_ANALYZE_DECK,
        INTENT_BUILD_DECK,
    )

    intent = getattr(getattr(ai_context, "intent", None), "request", None)
    if intent not in {INTENT_BUILD_DECK, INTENT_ANALYZE_DECK}:
        return False
    data = ai_context.primary_tool_data() if hasattr(ai_context, "primary_tool_data") else {}
    build = getattr(ai_context, "build", None)
    payload = build if isinstance(build, dict) and build else data
    sanity = sanity_payload_from_data(payload if isinstance(payload, dict) else {})
    if sanity is None:
        return False
    return not bool(sanity.get("passed", True))


def _configured_backend() -> str:
    return (settings.ghosteek_ai_backend or "qwen").strip().lower()


def _configured_mode() -> str:
    return (settings.ghosteek_ai_mode or MODE_AUTO).strip().lower()


def _resolve_provider(backend: str) -> LLMProvider | None:
    if backend in {"template", "default", ""}:
        return None
    if backend in {"qwen", "dashscope", "openai", "openai_compatible", "groq"}:
        return get_llm_provider(backend)
    if backend in {"ollama", "local"}:
        return get_llm_provider("ollama")
    return get_llm_provider(backend)


def _resolve_runtime_mode(provider: LLMProvider | None) -> str:
    """agent если LLM умеет tools; planner — только fallback / явный force."""
    configured = _configured_mode()
    # Явный planner — для отладки / когда LLM отключён оператором.
    if configured == MODE_PLANNER:
        return MODE_PLANNER
    if provider is not None and provider.supports_tools():
        return MODE_AGENT
    return MODE_PLANNER


async def _run_planner_fallback(
    ai_context: Any,
    plan: Plan,
    *,
    backend: str,
    provider: LLMProvider | None,
    reason: str,
) -> tuple[str, list[str], dict[str, Any]]:
    """Planner определяет tools только когда LLM недоступен или упал."""
    meta: dict[str, Any] = {
        "mode": MODE_PLANNER,
        "llm_backend": backend,
        "used_backend": backend,
        "response_time_ms": None,
        "fallback_reason": reason,
    }
    t0 = time.perf_counter()
    tool_results = await _CALLER.execute_plan(plan, ai_context)
    tool_names = [tr.tool for tr in tool_results]

    if backend in {"template", "default", ""} or provider is None:
        text = _TEMPLATE.generate(ai_context)
        meta["used_backend"] = "template"
        meta["llm_backend"] = "template" if backend in {"template", "default", ""} else backend
        meta["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(
            "ghosteek_ai mode=%s used_backend=template response_time_ms=%s fallback_reason=%s",
            MODE_PLANNER,
            meta["response_time_ms"],
            reason,
        )
        return text, tool_names, meta

    try:
        generator = get_response_generator(
            "ollama" if backend in {"ollama", "local"} else backend
        )
        agenerate = getattr(generator, "agenerate", None)
        if agenerate is None:
            raise RuntimeError("generator has no agenerate()")
        text = await agenerate(ai_context)
        if not isinstance(text, str):
            # ToolCallResult в fallback-path не ожидаем — на template
            raise RuntimeError("fallback generator returned non-text result")
        meta["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        meta["used_backend"] = "ollama" if backend in {"ollama", "local"} else backend
        logger.info(
            "ghosteek_ai mode=%s llm_backend=%s used_backend=%s response_time_ms=%s fallback_reason=%s",
            MODE_PLANNER,
            meta["llm_backend"],
            meta["used_backend"],
            meta["response_time_ms"],
            reason,
        )
        return text, tool_names, meta
    except Exception as exc:
        meta["fallback_reason"] = f"{reason}; template: {type(exc).__name__}: {exc}"
        meta["used_backend"] = "template"
        meta["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        logger.warning(
            "ghosteek_ai mode=%s used_backend=template response_time_ms=%s fallback_reason=%s",
            MODE_PLANNER,
            meta["response_time_ms"],
            meta["fallback_reason"],
        )
        text = _TEMPLATE.generate(ai_context)
        return text, tool_names, meta


async def _run_agent_mode(
    ai_context: Any,
    plan: Plan,
    *,
    backend: str,
    provider: LLMProvider,
) -> tuple[str, list[str], dict[str, Any]]:
    """LLM Tool Calling loop. При ошибке → Planner fallback."""
    meta: dict[str, Any] = {
        "mode": MODE_AGENT,
        "llm_backend": backend,
        "used_backend": backend,
        "response_time_ms": None,
        "fallback_reason": None,
        "agent_rounds": None,
        "used_tool_calling": False,
    }
    t0 = time.perf_counter()
    try:
        result = await run_llm_agent(
            ai_context,
            provider=provider,
            caller=_CALLER,
            registry=_REGISTRY,
            planner_plan=None,
        )
        meta["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        meta["used_backend"] = provider.name
        meta["agent_rounds"] = result.rounds
        meta["used_tool_calling"] = result.used_tool_calling
        logger.info(
            "ghosteek_ai mode=%s llm_backend=%s used_backend=%s response_time_ms=%s "
            "agent_rounds=%s used_tool_calling=%s tools=%s",
            MODE_AGENT,
            meta["llm_backend"],
            meta["used_backend"],
            meta["response_time_ms"],
            result.rounds,
            result.used_tool_calling,
            result.tool_names,
        )
        return result.text, result.tool_names, meta
    except Exception as exc:
        reason = f"agent_failed: {type(exc).__name__}: {exc}"
        logger.warning(
            "ghosteek_ai mode=%s llm_backend=%s fallback_reason=%s — Planner fallback",
            MODE_AGENT,
            backend,
            reason,
        )
        text, tool_names, fb_meta = await _run_planner_fallback(
            ai_context,
            plan,
            backend=backend,
            provider=provider,
            reason=reason,
        )
        fb_meta["agent_rounds"] = meta.get("agent_rounds")
        fb_meta["used_tool_calling"] = False
        return text, tool_names, fb_meta


async def ask_ghosteek_ai(
    message: str,
    user: User,
    *,
    context: dict[str, Any] | None = None,
) -> GhosteekAiResponse:
    """
    Orchestrator:

    Conversation → Intent
      → LLM available: PromptBuilder → Qwen → tool_calls → ToolCaller
           → role=tool → Qwen → … ≤5 → Safety → Response
      → LLM unavailable / error: Planner → ToolCaller(plan) → Template/LLM text
           → Safety → Response

    Planner не выбирает tools, пока LLM работает.
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

    # Plan строится заранее: seed args для AIContext + fallback, если LLM упадёт.
    # В Agent Mode plan НЕ исполняется и НЕ диктует tools.
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

    backend = _configured_backend()
    provider = _resolve_provider(backend)
    runtime_mode = _resolve_runtime_mode(provider)

    if runtime_mode == MODE_AGENT and provider is not None:
        raw_answer, tool_names, gen_meta = await _run_agent_mode(
            ai_context, plan, backend=backend, provider=provider
        )
    else:
        reason = (
            "llm_unavailable"
            if provider is None
            else (
                "mode_planner"
                if runtime_mode == MODE_PLANNER
                else "tools_unsupported"
            )
        )
        raw_answer, tool_names, gen_meta = await _run_planner_fallback(
            ai_context,
            plan,
            backend=backend,
            provider=provider,
            reason=reason,
        )

    # Sanity fail → только честный template-вердикт, без «как играть».
    if _sanity_blocks_explain(ai_context):
        raw_answer = _TEMPLATE.generate(ai_context)
        gen_meta = dict(gen_meta or {})
        gen_meta["used_backend"] = "template"
        gen_meta["fallback_reason"] = "deck_sanity_failed"

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
        "llm": {
            "mode": gen_meta.get("mode"),
            "backend": gen_meta.get("llm_backend"),
            "used_backend": gen_meta.get("used_backend"),
            "response_time_ms": gen_meta.get("response_time_ms"),
            "fallback_reason": gen_meta.get("fallback_reason"),
            "agent_rounds": gen_meta.get("agent_rounds"),
            "used_tool_calling": gen_meta.get("used_tool_calling"),
            "planner_suggestion": [t.name for t in plan.tools],
        },
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
            "has_battle": bool(
                ai_context.battle.raw or ai_context.battle.battle_index is not None
            ),
            "has_summary": bool(ai_context.conversation.summary),
        },
    }

    return GhosteekAiResponse(
        intent=intent_name,
        answer=answer,
        sources=sources,
        actions=actions,
        deck_card=dict(ai_context.deck_card) if isinstance(ai_context.deck_card, dict) else None,
    )
