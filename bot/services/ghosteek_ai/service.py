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

# Tools that never feed the LLM renderer (safe template responses only).
_TEMPLATE_ONLY_TOOLS = frozenset({"clarify", "unsupported"})

# Cloud + local: coach voice via LocalRendererPromptBuilder (facts → short trainer text).
_COACH_RENDERER_BACKENDS = frozenset(
    {"ollama", "local", "qwen", "dashscope", "openai", "openai_compatible", "groq"}
)
_COACH_CLOUD_BACKENDS = frozenset(
    {"qwen", "dashscope", "openai", "openai_compatible", "groq"}
)


def _uses_coach_renderer(backend: str) -> bool:
    """True when replies go through LocalRenderer (persona + FACTS), not free Agent prose."""
    return (backend or "").strip().lower() in _COACH_RENDERER_BACKENDS


def _sanity_blocks_explain(ai_context) -> bool:
    """Если Deck Sanity не пройден — не даём LLM оправдывать колоду игрока.

    Исключение: Builder уже вернул полную 8-карточную колоду. Это готовое
    предложение, его нельзя подменять текстом «доделай сам».
    """
    from bot.services.deck_sanity_validator import sanity_payload_from_data
    from bot.services.ghosteek_ai.deck_card import deck_card_from_build_data
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
    if not isinstance(payload, dict):
        payload = {}
    if intent == INTENT_BUILD_DECK:
        card = deck_card_from_build_data(payload)
        if card and len(card.get("deck") or []) >= 8:
            return False
    sanity = sanity_payload_from_data(payload)
    if sanity is None:
        return False
    return not bool(sanity.get("passed", True))


def _configured_backend() -> str:
    key = (settings.ghosteek_ai_backend or "qwen").strip().lower()
    # Railway has no local Ollama — if LLM_* is set, use cloud (Groq/Qwen).
    if key in {"ollama", "local"}:
        from bot.config import _running_on_railway

        has_cloud = bool(
            (settings.llm_api_key or "").strip()
            and (settings.llm_base_url or "").strip()
        )
        if _running_on_railway() and has_cloud:
            base = (settings.llm_base_url or "").lower()
            cloud = "groq" if "groq.com" in base else "qwen"
            logger.warning(
                "ghosteek_ai backend=%s on Railway with LLM_* set → using %s",
                key,
                cloud,
            )
            return cloud
    return key


def _configured_mode() -> str:
    return (settings.ghosteek_ai_mode or MODE_AUTO).strip().lower()


def _provider_model(provider: LLMProvider | None) -> str:
    if provider is None:
        return ""
    cfg = getattr(provider, "config", None)
    return str(getattr(cfg, "model", "") or "").strip()


def _runtime_capabilities(
    backend: str,
    provider: LLMProvider | None,
):
    """Единая capability-проверка для runtime selection."""
    from bot.services.ghosteek_ai.llm.runtime_capabilities import (
        resolve_cloud_capabilities,
        resolve_local_ollama_capabilities,
        warn_conflicting_ollama_tools_config,
        is_local_renderer_first_model,
    )
    from bot.services.ghosteek_ai.llm.base import LLMCapabilities

    key = (backend or "").strip().lower()
    if provider is not None:
        caps = provider.capabilities()
        # Conflict warning for local renderer-first + ENABLE_TOOLS
        if key in {"ollama", "local"}:
            cfg = getattr(provider, "config", None)
            model = _provider_model(provider) or (settings.ollama_model or "")
            extra = dict(getattr(cfg, "extra", None) or {})
            if is_local_renderer_first_model(model) and bool(extra.get("enable_tools")):
                warn_conflicting_ollama_tools_config(model)
        return caps

    if key in {"ollama", "local"}:
        return resolve_local_ollama_capabilities(
            settings.ollama_model,
            enable_tools_config=bool(getattr(settings, "ollama_enable_tools", False)),
        )
    if key in {"qwen", "dashscope", "openai", "openai_compatible", "groq"}:
        return resolve_cloud_capabilities(enable_tools=True)
    return LLMCapabilities()


def _force_planner_first(backend: str, provider: LLMProvider | None) -> bool:
    """When True, Agent Mode is not used — planner-first is mandatory."""
    caps = _runtime_capabilities(backend, provider)
    if not caps.supports_agent_loop:
        return True
    key = (backend or "").strip().lower()
    # Local with tools disabled → planner-first.
    if key in {"ollama", "local"}:
        if not caps.supports_tools:
            return True
    # Cloud auto: same coach path as Ollama (planner → tools → LocalRenderer).
    # Explicit GHOSTEEK_AI_MODE=agent still allows Agent (see _resolve_runtime_mode).
    if key in _COACH_CLOUD_BACKENDS:
        return _configured_mode() in {MODE_AUTO, ""}
    return False


def _is_local_renderer_first(backend: str, provider: LLMProvider | None) -> bool:
    """Local backend + renderer-first capability profile (e.g. qwen3 8B class)."""
    if (backend or "").strip().lower() not in {"ollama", "local"}:
        return False
    from bot.services.ghosteek_ai.llm.runtime_capabilities import (
        is_local_renderer_first_model,
    )

    model = _provider_model(provider) or (settings.ollama_model or "")
    return is_local_renderer_first_model(model)


# Back-compat alias for older tests / call sites.
_is_local_qwen3_8b = _is_local_renderer_first


def _resolve_provider(backend: str) -> LLMProvider | None:
    if backend in {"template", "default", ""}:
        return None
    if backend in {"qwen", "dashscope", "openai", "openai_compatible", "groq"}:
        return get_llm_provider(backend)
    if backend in {"ollama", "local"}:
        return get_llm_provider("ollama")
    return get_llm_provider(backend)


def _resolve_runtime_mode(
    provider: LLMProvider | None,
    *,
    backend: str = "",
) -> str:
    """agent только если capabilities.agent_loop; иначе planner-first."""
    configured = _configured_mode()
    if configured == MODE_PLANNER:
        return MODE_PLANNER

    caps = _runtime_capabilities(backend, provider)
    if not caps.supports_agent_loop or _force_planner_first(backend, provider):
        return MODE_PLANNER

    if configured == MODE_AGENT:
        if caps.supports_tools:
            return MODE_AGENT
        return MODE_PLANNER

    # auto
    if caps.supports_tools and caps.supports_agent_loop:
        return MODE_AGENT
    return MODE_PLANNER


def _successful_tool_results(results: list) -> list:
    """ToolResult, на которых разрешён LLM renderer (ok=True, не clarify/unsupported)."""
    out = []
    for r in results or []:
        name = str(getattr(r, "tool", "") or "")
        if name in _TEMPLATE_ONLY_TOOLS:
            continue
        if bool(getattr(r, "ok", False)):
            out.append(r)
    return out


def _make_renderer(backend: str, provider: LLMProvider | None):
    """Response generator bound to the request provider (shared session/config).

    Coach backends (Ollama + cloud Qwen/Groq) → LocalRendererPromptBuilder (voice layer).
    """
    from bot.services.ghosteek_ai.generator.llm_generator import (
        OllamaResponseGenerator,
        QwenResponseGenerator,
    )
    from bot.services.ghosteek_ai.llm.local_renderer import LocalRendererPromptBuilder

    key = (backend or "").strip().lower()
    if key in {"ollama", "local"}:
        return OllamaResponseGenerator(
            provider=provider,
            prompt_builder=LocalRendererPromptBuilder(),
        )
    if key in _COACH_CLOUD_BACKENDS:
        return QwenResponseGenerator(
            provider=provider,
            prompt_builder=LocalRendererPromptBuilder(),
        )
    return get_response_generator(key)


def _log_planner_turn(
    *,
    backend: str,
    model: str,
    intent: str,
    tools: list[str],
    tool_ok: list[bool],
    renderer_invoked: bool,
    reason: str,
) -> None:
    logger.info(
        "ghosteek_ai planner backend=%s model=%s intent=%s tools=%s "
        "tool_ok=%s renderer_invoked=%s reason=%s",
        backend,
        model or "-",
        intent or "-",
        tools,
        tool_ok,
        renderer_invoked,
        reason,
    )


async def _run_planner_fallback(
    ai_context: Any,
    plan: Plan,
    *,
    backend: str,
    provider: LLMProvider | None,
    reason: str,
) -> tuple[str, list[str], dict[str, Any]]:
    """Planner-first: INTENT_TOOL_MAP → tools → LLM renderer only after ok ToolResult.

    Used as:
    - primary path for local qwen3:8b / tools-disabled Ollama;
    - fallback when Agent Mode fails / LLM unavailable.
    """
    model = _provider_model(provider) or (
        (settings.ollama_model if backend in {"ollama", "local"} else settings.llm_model) or ""
    )
    intent = getattr(getattr(ai_context, "intent", None), "request", None) or plan.intent
    meta: dict[str, Any] = {
        "mode": MODE_PLANNER,
        "llm_backend": backend,
        "used_backend": backend,
        "response_time_ms": None,
        "fallback_reason": reason,
        "renderer_invoked": False,
        "tool_success": False,
        "model": model,
    }
    t0 = time.perf_counter()

    tool_names: list[str] = []
    tool_ok_flags: list[bool] = []

    # Conversational (INTENT_CHAT): нет tools → LLM voice на persona facts.
    # Прочие no-tool планы — только template.
    if not plan.tools:
        intent_l = str(intent or "").strip().lower()
        if (
            _uses_coach_renderer(backend)
            and intent_l == "chat"
            and provider is not None
        ):
            from bot.services.ghosteek_ai.llm.local_renderer import (
                attach_conversational_facts,
                attach_render_facts,
                can_reuse_last_facts_for_followup,
            )

            # Small talk никогда не берёт старый CR ToolResult.
            # «А почему?» после игрового ответа — reuse last_render_facts.
            if can_reuse_last_facts_for_followup(ai_context):
                attach_render_facts(ai_context)
                meta["followup_reuse_facts"] = True
                meta["tool_success"] = False
            else:
                attach_conversational_facts(ai_context)
                meta["conversational"] = True
                meta["tool_success"] = False
        else:
            text = _TEMPLATE.generate(ai_context)
            meta["used_backend"] = "template"
            meta["fallback_reason"] = f"{reason};no_plan_tools"
            meta["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            _log_planner_turn(
                backend=backend,
                model=model,
                intent=intent,
                tools=[],
                tool_ok=[],
                renderer_invoked=False,
                reason=meta["fallback_reason"],
            )
            return text, [], meta
    else:
        tool_results = await _CALLER.execute_plan(plan, ai_context)
        tool_names = [tr.tool for tr in tool_results]
        tool_ok_flags = [bool(tr.ok) for tr in tool_results]
        success = _successful_tool_results(tool_results)
        meta["tool_success"] = bool(success)

        # Failed / clarify / unsupported → template, never LLM.
        # Exceptions:
        # - local follow-up («подробнее» / «а почему?») с сохранёнными facts;
        # - conversational / soft-clarify с persona/capability-facts only.
        if not success:
            from bot.services.ghosteek_ai.llm.local_renderer import (
                attach_capability_clarify_facts,
                attach_conversational_facts,
                attach_render_facts,
                can_render_capability_clarify,
                can_render_conversational,
                can_reuse_last_facts_for_followup,
            )

            if _uses_coach_renderer(backend) and can_reuse_last_facts_for_followup(
                ai_context
            ):
                attach_render_facts(ai_context)
                meta["tool_success"] = False
                meta["followup_reuse_facts"] = True
            elif _uses_coach_renderer(backend) and (
                can_render_conversational(ai_context)
                or can_render_capability_clarify(ai_context)
            ):
                if can_render_conversational(ai_context):
                    attach_conversational_facts(ai_context)
                    meta["conversational"] = True
                else:
                    attach_capability_clarify_facts(ai_context)
                    meta["capability_clarify"] = True
                meta["tool_success"] = False
            else:
                text = _TEMPLATE.generate(ai_context)
                meta["used_backend"] = "template"
                meta["fallback_reason"] = f"{reason};tool_failed_or_clarify"
                meta["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                _log_planner_turn(
                    backend=backend,
                    model=model,
                    intent=intent,
                    tools=tool_names,
                    tool_ok=tool_ok_flags,
                    renderer_invoked=False,
                    reason=meta["fallback_reason"],
                )
                return text, tool_names, meta

    if backend in {"template", "default", ""} or provider is None:
        text = _TEMPLATE.generate(ai_context)
        meta["used_backend"] = "template"
        meta["llm_backend"] = "template" if backend in {"template", "default", ""} else backend
        meta["fallback_reason"] = f"{reason};template_backend"
        meta["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        _log_planner_turn(
            backend=backend,
            model=model,
            intent=intent,
            tools=tool_names,
            tool_ok=tool_ok_flags,
            renderer_invoked=False,
            reason=meta["fallback_reason"],
        )
        return text, tool_names, meta

    # LLM = renderer only (no tool schemas → cannot invent tool calls as primary path).
    try:
        render_kwargs: dict[str, Any] = {}
        if _uses_coach_renderer(backend):
            from bot.services.ghosteek_ai.llm.local_renderer import (
                attach_render_facts,
                renderer_generate_kwargs,
            )

            # conversational / capability уже положили FACTS — не перетирать.
            if not meta.get("capability_clarify") and not meta.get("conversational"):
                attach_render_facts(ai_context)
            render_kwargs = renderer_generate_kwargs(
                conversational=bool(
                    meta.get("conversational") or meta.get("capability_clarify")
                ),
                backend=backend,
            )
        generator = _make_renderer(backend, provider)
        agenerate = getattr(generator, "agenerate", None)
        if agenerate is None:
            raise RuntimeError("generator has no agenerate()")
        text = await agenerate(ai_context, tools=None, **render_kwargs)
        if not isinstance(text, str):
            raise RuntimeError("planner renderer returned non-text result")
        meta["renderer_invoked"] = True
        meta["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        meta["used_backend"] = "ollama" if backend in {"ollama", "local"} else backend
        _log_planner_turn(
            backend=backend,
            model=model,
            intent=intent,
            tools=tool_names,
            tool_ok=tool_ok_flags,
            renderer_invoked=True,
            reason=reason,
        )
        return text, tool_names, meta
    except Exception as exc:
        meta["fallback_reason"] = f"{reason}; template: {type(exc).__name__}: {exc}"
        meta["used_backend"] = "template"
        meta["renderer_invoked"] = False
        meta["response_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        logger.warning(
            "ghosteek_ai planner renderer_failed backend=%s model=%s intent=%s err=%s",
            backend,
            model or "-",
            intent or "-",
            type(exc).__name__,
        )
        _log_planner_turn(
            backend=backend,
            model=model,
            intent=intent,
            tools=tool_names,
            tool_ok=tool_ok_flags,
            renderer_invoked=False,
            reason=meta["fallback_reason"],
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
    """LLM Tool Calling loop (cloud / strong models). При ошибке → Planner path."""
    meta: dict[str, Any] = {
        "mode": MODE_AGENT,
        "llm_backend": backend,
        "used_backend": backend,
        "response_time_ms": None,
        "fallback_reason": None,
        "agent_rounds": None,
        "used_tool_calling": False,
        "model": _provider_model(provider),
    }
    t0 = time.perf_counter()
    logger.info(
        "ghosteek_ai agent backend=%s model=%s intent=%s",
        backend,
        meta["model"] or "-",
        getattr(getattr(ai_context, "intent", None), "request", None) or plan.intent,
    )
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

        # Coach voice parity: after tools, re-render via LocalRenderer (not free Agent prose).
        text = result.text
        if _uses_coach_renderer(backend) and result.tool_names:
            try:
                from bot.services.ghosteek_ai.llm.local_renderer import (
                    attach_render_facts,
                    renderer_generate_kwargs,
                )

                attach_render_facts(ai_context)
                generator = _make_renderer(backend, provider)
                agenerate = getattr(generator, "agenerate", None)
                if agenerate is not None:
                    voiced = await agenerate(
                        ai_context,
                        tools=None,
                        **renderer_generate_kwargs(backend=backend),
                    )
                    if isinstance(voiced, str) and voiced.strip():
                        text = voiced
                        meta["renderer_invoked"] = True
            except Exception:
                logger.warning(
                    "ghosteek_ai agent LocalRenderer re-voice failed; keeping agent text",
                    exc_info=True,
                )

        logger.info(
            "ghosteek_ai mode=%s llm_backend=%s used_backend=%s response_time_ms=%s "
            "agent_rounds=%s used_tool_calling=%s tools=%s renderer_invoked=%s",
            MODE_AGENT,
            meta["llm_backend"],
            meta["used_backend"],
            meta["response_time_ms"],
            result.rounds,
            result.used_tool_calling,
            result.tool_names,
            meta.get("renderer_invoked", False),
        )
        return text, result.tool_names, meta
    except Exception as exc:
        reason = f"agent_failed: {type(exc).__name__}: {exc}"
        logger.warning(
            "ghosteek_ai mode=%s llm_backend=%s fallback_reason=%s — Planner path",
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

    Conversation → Intent → Plan (INTENT_TOOL_MAP)
      → coach backends (Ollama / Qwen / Groq): ToolCaller(plan) → (ok ToolResult) → LocalRenderer
      → explicit Agent mode: PromptBuilder → LLM tool_calls → LocalRenderer re-voice → Safety
      → tool fail / clarify / unsupported: Template only (no LLM)
    """
    session = ConversationManager.get_or_create(user.telegram_id)
    ConversationManager.add_user_message(session, message)

    req_ctx = ConversationManager.merge_request_context(session, context)
    # Local renderer follow-ups: previous facts / brief answer only (not full history).
    if isinstance(session.last_render_facts, dict) and session.last_render_facts:
        req_ctx["last_render_facts"] = dict(session.last_render_facts)
    if session.last_answer_brief:
        req_ctx["last_answer_brief"] = session.last_answer_brief
    elif session.last_assistant_messages:
        req_ctx["last_answer_brief"] = str(session.last_assistant_messages[-1])[:180]

    # Accepted CR replay is known, but Stage 4 coaching is not ready yet.
    from bot.services.ghosteek_ai.replay_followup import (
        is_replay_coaching_request,
        reply_replay_pending_analysis,
        resolve_replay_meta,
    )

    replay_meta = resolve_replay_meta(session.last_replay, req_ctx)
    if replay_meta and is_replay_coaching_request(message):
        # Prefer full session payload (coach_reply) over normalized-only meta.
        answer_meta = dict(session.last_replay or {})
        answer_meta.update(replay_meta)
        answer = reply_replay_pending_analysis(answer_meta)
        intent = "replay_coach" if answer_meta.get("coach_reply") else "replay_pending"
        ConversationManager.add_assistant_message(session, answer, intent=intent)
        session.last_answer_brief = answer[:180]
        session.active_topic = "replay"
        ConversationManager.save(user.telegram_id, session)
        return GhosteekAiResponse(
            intent=intent,
            answer=answer,
            sources={
                "intent": intent,
                "replay": replay_meta,
                "stage": "coach" if intent == "replay_coach" else "detection_only",
                "coach_source": answer_meta.get("coach_source"),
            },
        )

    context_cards: list[str] = []
    if isinstance(req_ctx.get("cards"), list):
        context_cards = [c for c in req_ctx["cards"] if isinstance(c, str)]

    detected = detect_intent(message, context_cards=context_cards)
    detected = ConversationManager.apply_followup_enrichment(
        session, detected, message, req_ctx
    )
    if getattr(detected, "build_limit", None):
        req_ctx["build_limit"] = int(detected.build_limit)
    if getattr(detected, "prefer_alternative", False):
        req_ctx["prefer_alternative"] = True

    # Plan: seed args + executed in planner-first / agent fallback.
    plan = Planner.plan(detected)
    tool_args = dict(plan.tools[0].args) if plan.tools else {}
    if req_ctx.get("exclude_decks") and "exclude_decks" not in tool_args:
        tool_args["exclude_decks"] = req_ctx["exclude_decks"]
    if req_ctx.get("build_limit") and "build_limit" not in tool_args:
        tool_args["build_limit"] = req_ctx["build_limit"]
    if req_ctx.get("prefer_alternative") and "prefer_alternative" not in tool_args:
        tool_args["prefer_alternative"] = True

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
    runtime_mode = _resolve_runtime_mode(provider, backend=backend)
    runtime_model = _provider_model(provider) or (
        (settings.ollama_model or "").strip()
        if backend in {"ollama", "local"}
        else ""
    )
    # Diagnostic only: backend / model / mode (no prompts, keys, or user text).
    logger.info(
        "ghosteek_ai runtime backend=%s model=%s mode=%s provider=%s",
        backend,
        runtime_model or "-",
        runtime_mode,
        getattr(provider, "name", None) or "none",
    )

    try:
        # Chat / empty-plan → всегда planner conversational path (не Agent tool-loop).
        if not plan.tools or str(detected.intent or "") == "chat":
            raw_answer, tool_names, gen_meta = await _run_planner_fallback(
                ai_context,
                plan,
                backend=backend,
                provider=provider,
                reason="conversational_no_tools",
            )
        elif runtime_mode == MODE_AGENT and provider is not None:
            raw_answer, tool_names, gen_meta = await _run_agent_mode(
                ai_context, plan, backend=backend, provider=provider
            )
        else:
            reason = (
                "llm_unavailable"
                if provider is None
                else (
                    "local_planner_first"
                    if _force_planner_first(backend, provider)
                    else (
                        "mode_planner"
                        if runtime_mode == MODE_PLANNER
                        else "tools_unsupported"
                    )
                )
            )
            raw_answer, tool_names, gen_meta = await _run_planner_fallback(
                ai_context,
                plan,
                backend=backend,
                provider=provider,
                reason=reason,
            )
    finally:
        if provider is not None:
            try:
                await provider.close()
            except Exception:
                logger.debug("ghosteek_ai provider.close failed", exc_info=True)

    # Sanity fail → только честный template-вердикт, без «как играть».
    if _sanity_blocks_explain(ai_context):
        raw_answer = _TEMPLATE.generate(ai_context)
        gen_meta = dict(gen_meta or {})
        gen_meta["used_backend"] = "template"
        gen_meta["fallback_reason"] = "deck_sanity_failed"
        gen_meta["renderer_invoked"] = False

    answer = SafetyLayer.apply(raw_answer, ai_context)

    intent_name = ai_context.intent.request
    topic_update = intent_name if intent_name != "chat" else None
    ConversationManager.update_from_ai_context(
        session,
        intent=intent_name,
        service=ai_context.intent.service,
        data=ai_context.data,
        ok=ai_context.ok,
        active_topic=topic_update,
        tools=tool_names,
    )
    # Persist compact facts for next local follow-up («подробнее» / «а почему?»).
    if isinstance(getattr(ai_context, "render_facts", None), dict) and ai_context.render_facts:
        session.last_render_facts = dict(ai_context.render_facts)
    if answer:
        session.last_answer_brief = str(answer)[:180]
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
            "model": gen_meta.get("model"),
            "response_time_ms": gen_meta.get("response_time_ms"),
            "fallback_reason": gen_meta.get("fallback_reason"),
            "agent_rounds": gen_meta.get("agent_rounds"),
            "used_tool_calling": gen_meta.get("used_tool_calling"),
            "renderer_invoked": gen_meta.get("renderer_invoked"),
            "tool_success": gen_meta.get("tool_success"),
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

    deck_cards: list[dict] = []
    data_cards = (getattr(ai_context, "data", None) or {}).get("deck_cards")
    if isinstance(data_cards, list):
        deck_cards = [
            dict(c) for c in data_cards if isinstance(c, dict) and c.get("deck")
        ]
    if not deck_cards and ai_context.deck.built_decks:
        from bot.services.ghosteek_ai.deck_card import (
            deck_card_from_entry,
            format_arena_label,
        )

        arena_label = format_arena_label(ai_context.arena.arena_id, ai_context.arena.trophies)
        for entry in ai_context.deck.built_decks[:3]:
            if not isinstance(entry, dict):
                continue
            built = deck_card_from_entry(entry, arena=arena_label)
            if built:
                deck_cards.append(built)
    primary_deck = (
        deck_cards[0]
        if deck_cards
        else (dict(ai_context.deck_card) if isinstance(ai_context.deck_card, dict) else None)
    )

    return GhosteekAiResponse(
        intent=intent_name,
        answer=answer,
        sources=sources,
        actions=actions,
        deck_card=primary_deck,
        deck_cards=deck_cards,
    )
