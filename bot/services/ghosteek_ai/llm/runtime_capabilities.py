"""Runtime capability resolution for Ghosteek AI backends.

Не привязывает архитектуру навсегда к одному имени модели.
Профили задают family/size tags; cloud Agent Mode не затрагивается.
"""

from __future__ import annotations

import logging
from typing import Any

from bot.services.ghosteek_ai.llm.base import LLMCapabilities, LLMConfig

logger = logging.getLogger(__name__)

# Local models that must stay planner-first → ToolResult → renderer (no Agent loop).
# Match: ALL substrings present in normalized model id (order-independent).
# Добавляйте сюда новые слабые local-модели; не хардкодьте ветки в service.py.
LOCAL_RENDERER_FIRST_PROFILES: tuple[tuple[str, ...], ...] = (
    ("qwen3", "8b"),
    ("qwen3.5", "9b"),
    ("qwen35", "9b"),
)


# Явный allowlist local-моделей, которым разрешён Agent Mode (tool loop).
# Пусто по умолчанию — local Agent только после явного объявления compatible.
LOCAL_AGENT_COMPATIBLE_PROFILES: tuple[tuple[str, ...], ...] = ()

_warned_conflicts: set[str] = set()


def normalize_model_id(model: str | None) -> str:
    return (model or "").strip().lower().replace(" ", "")


def _profile_matches(model_id: str, profile: tuple[str, ...]) -> bool:
    if not model_id or not profile:
        return False
    return all(part.lower() in model_id for part in profile)


def matches_any_profile(model: str | None, profiles: tuple[tuple[str, ...], ...]) -> bool:
    mid = normalize_model_id(model)
    return any(_profile_matches(mid, p) for p in profiles)


def is_local_renderer_first_model(model: str | None) -> bool:
    """True для local-моделей с профилем renderer-first (напр. qwen3 8B class)."""
    mid = normalize_model_id(model)
    if matches_any_profile(mid, LOCAL_AGENT_COMPATIBLE_PROFILES):
        return False
    return matches_any_profile(mid, LOCAL_RENDERER_FIRST_PROFILES)


def is_local_agent_compatible_model(model: str | None) -> bool:
    return matches_any_profile(model, LOCAL_AGENT_COMPATIBLE_PROFILES)


def _extra_flag(extra: dict[str, Any], key: str) -> bool | None:
    if key not in extra:
        return None
    return bool(extra.get(key))


def resolve_local_ollama_capabilities(
    model: str | None,
    *,
    enable_tools_config: bool = False,
    extra: dict[str, Any] | None = None,
) -> LLMCapabilities:
    """Capabilities для Ollama/local runtime.

    renderer-first профиль:
      supports_tools=False, supports_agent_loop=False, supports_renderer=True
      даже если OLLAMA_ENABLE_TOOLS=true (конфликт → warning).
    """
    extra = dict(extra or {})
    mid = normalize_model_id(model)

    # Explicit per-config overrides (optional).
    force_planner = _extra_flag(extra, "force_planner_first")
    allow_agent = _extra_flag(extra, "allow_agent_loop")

    if allow_agent is True or is_local_agent_compatible_model(mid):
        tools = bool(enable_tools_config)
        return LLMCapabilities(
            tools=tools,
            stream=True,
            json_mode=False,
            agent_loop=tools,
            renderer=True,
        )

    renderer_first = force_planner is True or (
        force_planner is not False and is_local_renderer_first_model(mid)
    )

    if renderer_first:
        if enable_tools_config:
            warn_conflicting_ollama_tools_config(mid)
        return LLMCapabilities(
            tools=False,
            stream=True,
            json_mode=False,
            agent_loop=False,
            renderer=True,
        )

    # Other local models: respect enable_tools; Agent only when tools on.
    tools = bool(enable_tools_config)
    return LLMCapabilities(
        tools=tools,
        stream=True,
        json_mode=False,
        agent_loop=tools,
        renderer=True,
    )


def resolve_cloud_capabilities(*, enable_tools: bool = True) -> LLMCapabilities:
    """Cloud Qwen/Groq — Agent Mode compatible."""
    return LLMCapabilities(
        tools=bool(enable_tools),
        stream=False,
        json_mode=False,
        agent_loop=bool(enable_tools),
        renderer=False,
    )


def capabilities_from_config(config: LLMConfig | None) -> LLMCapabilities:
    if config is None:
        return LLMCapabilities()
    provider = (config.provider or "").strip().lower()
    extra = dict(config.extra or {})
    if provider in {"ollama", "local"}:
        return resolve_local_ollama_capabilities(
            config.model,
            enable_tools_config=bool(extra.get("enable_tools", False)),
            extra=extra,
        )
    if provider in {"qwen", "groq", "dashscope", "openai", "openai_compatible"}:
        return resolve_cloud_capabilities(
            enable_tools=bool(extra.get("enable_tools", True)),
        )
    return LLMCapabilities(
        tools=bool(extra.get("enable_tools", False)),
        stream=False,
        agent_loop=bool(extra.get("enable_tools", False)),
        renderer=False,
    )


def warn_conflicting_ollama_tools_config(model: str) -> None:
    """Startup/runtime warning: ENABLE_TOOLS ignored for renderer-first local models."""
    key = normalize_model_id(model) or "unknown"
    if key in _warned_conflicts:
        return
    _warned_conflicts.add(key)
    logger.warning(
        "ghosteek_ai config conflict: OLLAMA_ENABLE_TOOLS=true for model=%s, "
        "but local runtime forces planner-first "
        "(supports_tools=false, supports_agent_loop=false, supports_renderer=true). "
        "Agent Mode will not be used. Unset OLLAMA_ENABLE_TOOLS or declare the model "
        "in LOCAL_AGENT_COMPATIBLE_PROFILES if Agent is intentional.",
        model or key,
    )


def reset_capability_warnings() -> None:
    """Tests only."""
    _warned_conflicts.clear()
