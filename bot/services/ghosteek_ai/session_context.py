"""Session Context Ghosteek AI — память текущего диалога (in-memory, TTL)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Сессия считается законченной после простоя
SESSION_TTL_SECONDS = 45 * 60

_sessions: dict[int, "AiSessionContext"] = {}


@dataclass
class AiSessionContext:
    """Контекст одного пользователя на время сессии."""

    last_deck: list[str] = field(default_factory=list)
    last_opponent_deck: list[str] = field(default_factory=list)
    last_battle_index: int | None = None
    last_intent: str | None = None
    last_service: str | None = None
    last_analysis: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def expired(self, *, now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        return (ts - self.updated_at) > SESSION_TTL_SECONDS

    def to_public(self) -> dict[str, Any]:
        return {
            "last_deck": list(self.last_deck),
            "last_opponent_deck": list(self.last_opponent_deck),
            "last_battle_index": self.last_battle_index,
            "last_intent": self.last_intent,
            "last_service": self.last_service,
            "has_deck": len(self.last_deck) >= 8,
            "has_matchup": len(self.last_deck) >= 8 and len(self.last_opponent_deck) >= 8,
            "has_battle": self.last_battle_index is not None,
        }


def get_session(telegram_id: int) -> AiSessionContext | None:
    session = _sessions.get(telegram_id)
    if session is None:
        return None
    if session.expired():
        _sessions.pop(telegram_id, None)
        return None
    return session


def get_or_create_session(telegram_id: int) -> AiSessionContext:
    session = get_session(telegram_id)
    if session is None:
        session = AiSessionContext()
        _sessions[telegram_id] = session
    session.touch()
    return session


def clear_session(telegram_id: int) -> None:
    _sessions.pop(telegram_id, None)


def merge_request_context(
    session: AiSessionContext | None,
    request_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Слить явный context запроса с сессией (запрос имеет приоритет)."""
    ctx: dict[str, Any] = dict(request_context or {})
    if session is None:
        return ctx

    cards = ctx.get("cards")
    if not (isinstance(cards, list) and len([c for c in cards if isinstance(c, str)]) >= 8):
        if len(session.last_deck) >= 8:
            ctx["cards"] = list(session.last_deck)

    opp = ctx.get("opponent_cards")
    if not (isinstance(opp, list) and len([c for c in opp if isinstance(c, str)]) >= 8):
        if len(session.last_opponent_deck) >= 8:
            ctx["opponent_cards"] = list(session.last_opponent_deck)

    ctx["session"] = session.to_public()
    return ctx


def update_session_from_payload(
    session: AiSessionContext,
    *,
    intent: str,
    service: str | None,
    payload: dict[str, Any],
) -> None:
    """Обновить сессию после ответа сервиса (только при ok или полезных данных)."""
    data = payload.get("data") or {}
    ok = bool(payload.get("ok"))

    session.last_intent = intent
    session.last_service = service
    session.touch()

    if not ok and not data:
        return

    deck = data.get("deck")
    if isinstance(deck, list) and len(deck) >= 8:
        session.last_deck = [c for c in deck if isinstance(c, str)][:8]

    user_deck = data.get("user_deck")
    if isinstance(user_deck, list) and len(user_deck) >= 8:
        session.last_deck = [c for c in user_deck if isinstance(c, str)][:8]

    # Builder templates — первая колода как текущая опора
    if intent == "build_deck":
        core = data.get("core")
        if isinstance(core, list) and core:
            # ядро не полное — но если есть готовая колода в decks, берём её
            pass
        decks = data.get("decks") or []
        if decks:
            first = decks[0] if isinstance(decks[0], dict) else {}
            cards = first.get("cards") or []
            names: list[str] = []
            if isinstance(cards, list):
                for c in cards:
                    if isinstance(c, str):
                        names.append(c)
                    elif isinstance(c, dict) and c.get("name"):
                        names.append(str(c["name"]))
            if len(names) >= 8:
                session.last_deck = names[:8]

    opp = data.get("opponent_deck")
    if isinstance(opp, list) and len(opp) >= 8:
        session.last_opponent_deck = [c for c in opp if isinstance(c, str)][:8]

    if data.get("battle_index") is not None:
        try:
            session.last_battle_index = int(data["battle_index"])
        except (TypeError, ValueError):
            pass

    # Компактный снимок последнего анализа (без огромных деревьев)
    snapshot: dict[str, Any] = {"intent": intent, "ok": ok}
    for key in (
        "synergy_score",
        "score",
        "rating",
        "won",
        "opponent_name",
        "matchup_score",
        "archetype",
        "mode",
        "title",
        "key",
    ):
        if key in data and data[key] is not None:
            snapshot[key] = data[key]
    if session.last_deck:
        snapshot["deck"] = list(session.last_deck)
    if session.last_opponent_deck:
        snapshot["opponent_deck"] = list(session.last_opponent_deck)
    session.last_analysis = snapshot


def clear_all_sessions() -> None:
    _sessions.clear()
