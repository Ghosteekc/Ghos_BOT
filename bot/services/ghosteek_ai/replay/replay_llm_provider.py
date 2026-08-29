"""LLM provider selection for replay text renderers (moments, summary, coach)."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

# Separate from vision model — avoids sharing qwen3.6 TPM with frame analysis.
DEFAULT_REPLAY_WORDING_MODEL = "openai/gpt-oss-20b"


def replay_wording_provider() -> Any:
    """Cloud text model for replay wording; never local Ollama unless backend=ollama."""
    from bot.config import settings
    from bot.services.ghosteek_ai.llm.provider import (
        OllamaProvider,
        QwenLLMProvider,
        ollama_config_from_settings,
        qwen_config_from_settings,
    )

    backend = (settings.ghosteek_ai_backend or "").strip().lower()
    if backend in {"ollama", "local"}:
        return OllamaProvider(ollama_config_from_settings())

    use_cloud = backend in {"qwen", "dashscope", "openai", "openai_compatible", "groq"} or (
        (settings.llm_api_key or "").strip() and (settings.llm_base_url or "").strip()
    )
    if use_cloud:
        cfg = qwen_config_from_settings()
        model = (
            os.environ.get("REPLAY_WORDING_MODEL", "").strip()
            or DEFAULT_REPLAY_WORDING_MODEL
        )
        cfg = replace(
            cfg,
            model=model,
            max_tokens=min(int(cfg.max_tokens or 512), 280),
            extra={**dict(cfg.extra or {}), "reasoning_format": None},
        )
        return QwenLLMProvider(cfg)

    return OllamaProvider(ollama_config_from_settings())
