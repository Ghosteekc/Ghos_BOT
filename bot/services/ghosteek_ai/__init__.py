"""Ghosteek AI — оркестратор поверх существующих CR-сервисов."""

from bot.services.ghosteek_ai.service import ask_ghosteek_ai
from bot.services.ghosteek_ai.voice import PERSONA

__all__ = ["ask_ghosteek_ai", "PERSONA"]
