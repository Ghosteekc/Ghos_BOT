"""Внешние зависимости Tool Layer — единая точка для patch в тестах.

`router.py` реэкспортирует эти символы, поэтому
`patch("bot.services.ghosteek_ai.router.X")` продолжает работать,
если tools вызывают их через этот модуль *и* через router-алиасы.

Фактически tools импортируют отсюда; router реэкспортирует отсюда же.
Патч router.X заменяет атрибут на router, поэтому tools должны
обращаться к router при resolve/analyze — см. `_call` helpers ниже.
"""

from __future__ import annotations

from typing import Any

from bot.models.database import User
from bot.services.battle_service import load_and_persist
from bot.services.card_matchups import calculate_deck_synergy
from bot.services.recommendation_engine import RecommendationEngine


async def resolve_player_deck(user: User, fallback: list[str]) -> list[str]:
    if len(fallback) >= 8:
        return fallback[:8]
    tag = user.player_tag or ""
    if not tag:
        return fallback
    try:
        from bot.services.clash_api import ClashRoyaleClient
        from bot.services.top_players import _cards_from_current_deck

        client = ClashRoyaleClient()
        try:
            player = await client.get_player(tag)
            parsed = _cards_from_current_deck(player)
            names = [c["name"] for c in parsed if c.get("name")]
            if len(names) >= 8:
                return names[:8]
        finally:
            await client.close()
    except Exception:
        pass
    battles = await load_and_persist(user)
    if battles:
        team = battles[0].get("team", [{}])[0]
        names = [c.get("name") for c in team.get("cards", []) if c.get("name")]
        if len(names) >= 8:
            return names[:8]
    return fallback


async def call_resolve_player_deck(user: User, fallback: list[str]) -> list[str]:
    """Вызов через router-shim, чтобы работали unittest patches на router.*."""
    from bot.services.ghosteek_ai import router as router_mod

    return await router_mod._resolve_player_deck(user, fallback)


def call_recommendation_analyze(deck: list[str], *, apply_swaps: bool) -> Any:
    from bot.services.ghosteek_ai import router as router_mod

    return router_mod.RecommendationEngine.analyze(deck, apply_swaps=apply_swaps)


def call_calculate_deck_synergy(deck: list[str]) -> Any:
    from bot.services.ghosteek_ai import router as router_mod

    return router_mod.calculate_deck_synergy(deck)


async def call_load_and_persist(user: User, **kwargs: Any) -> Any:
    from bot.services.ghosteek_ai import router as router_mod

    return await router_mod.load_and_persist(user, **kwargs)
