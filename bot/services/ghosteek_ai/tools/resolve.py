"""Резолв колоды — тонкая обёртка над deps."""

from __future__ import annotations

from bot.models.database import User
from bot.services.ghosteek_ai.tools.deps import (
    call_resolve_player_deck,
    resolve_player_deck,
)

__all__ = ["resolve_player_deck", "call_resolve_player_deck", "_resolve_player_deck"]

_resolve_player_deck = resolve_player_deck
