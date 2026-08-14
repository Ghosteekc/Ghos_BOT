"""Replay video upload, validation, and heuristic CR detection (stage 3)."""

from bot.services.ghosteek_ai.replay.hud_analyzer import HeuristicHudAnalyzer
from bot.services.ghosteek_ai.replay.models import ReplayAnalyzeOutcome, ReplayDetection
from bot.services.ghosteek_ai.replay.sampler import FrameSampler
from bot.services.ghosteek_ai.replay.service import ReplayAnalyzeService, get_replay_service
from bot.services.ghosteek_ai.replay.validator import (
    MAX_DURATION_SECONDS,
    MAX_SIZE_BYTES,
    ReplayError,
    ReplayMeta,
)

__all__ = [
    "FrameSampler",
    "HeuristicHudAnalyzer",
    "MAX_DURATION_SECONDS",
    "MAX_SIZE_BYTES",
    "ReplayAnalyzeOutcome",
    "ReplayAnalyzeService",
    "ReplayDetection",
    "ReplayError",
    "ReplayMeta",
    "get_replay_service",
]
