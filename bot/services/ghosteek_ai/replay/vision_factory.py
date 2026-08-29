"""Select replay VisionAnalyzer backend (Groq by default, Ollama optional)."""

from __future__ import annotations

import logging
import os

from bot.services.ghosteek_ai.replay.vision_analyzer import VisionAnalyzer

logger = logging.getLogger(__name__)


def vision_provider() -> str:
    raw = (os.environ.get("REPLAY_VISION_PROVIDER") or "groq").strip().lower()
    if raw in {"ollama", "local"}:
        return "ollama"
    if raw in {"groq", "cloud"}:
        return "groq"
    logger.warning("unknown REPLAY_VISION_PROVIDER=%r — using groq", raw)
    return "groq"


def create_vision_analyzer() -> VisionAnalyzer:
    """Build the configured vision adapter. Used only when REPLAY_VISION_ENABLED=1."""
    provider = vision_provider()
    if provider == "ollama":
        from bot.services.ghosteek_ai.replay.ollama_vision_analyzer import OllamaVisionAnalyzer

        return OllamaVisionAnalyzer()
    from bot.services.ghosteek_ai.replay.groq_vision_analyzer import GroqVisionAnalyzer

    return GroqVisionAnalyzer()
