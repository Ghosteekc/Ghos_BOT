"""LLM provider selection for replay text renderers (moments, summary, coach)."""

from __future__ import annotations

from typing import Any


def replay_wording_provider() -> Any:
    """Cloud Groq/Qwen on Railway; local Ollama only when explicitly configured."""
    from bot.config import settings
    from bot.services.ghosteek_ai.llm.provider import (
        OllamaProvider,
        get_llm_provider,
        ollama_config_from_settings,
    )

    backend = (settings.ghosteek_ai_backend or "").strip().lower()
    if backend in {"ollama", "local"}:
        return OllamaProvider(ollama_config_from_settings())
    if backend in {"qwen", "dashscope", "openai", "openai_compatible", "groq"}:
        return get_llm_provider(backend)
    if (settings.llm_api_key or "").strip() and (settings.llm_base_url or "").strip():
        base = (settings.llm_base_url or "").lower()
        return get_llm_provider("groq" if "groq.com" in base else "qwen")
    return OllamaProvider(ollama_config_from_settings())
