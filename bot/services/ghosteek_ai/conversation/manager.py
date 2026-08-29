"""Conversation Manager — оркестрация памяти диалога через MemoryProvider."""

from __future__ import annotations

import time
from typing import Any

from bot.services.ghosteek_ai.conversation.state import (
    MAX_ASSISTANT_MESSAGES,
    MAX_FOLLOWUPS,
    MAX_QUESTIONS,
    MAX_TOOLS,
    MAX_USER_MESSAGES,
    SESSION_TTL_SECONDS,
    ConversationState,
)
from bot.services.ghosteek_ai.memory.provider import get_memory_provider
from bot.services.ghosteek_ai.memory.summary import maybe_compress
from bot.services.ghosteek_ai.models import ConversationMessage, FollowUpEvent

# Alias для совместимости
AiSessionContext = ConversationState


def _compact_recommendation(data: dict[str, Any]) -> dict[str, Any]:
    rec = data.get("recommendation")
    if not isinstance(rec, dict):
        rec = {}
    coaching = rec.get("coaching") or {}
    plan = rec.get("improvement_plan") or {}
    gp = rec.get("game_plan") or {}
    return {
        "synergy_score": data.get("synergy_score"),
        "play_style": coaching.get("play_style"),
        "how_to_win": gp.get("how_to_win"),
        "improvement_needed": plan.get("needed"),
        "steps": (plan.get("steps") or [])[:3],
        "deck": list(data.get("original_deck") or data.get("deck") or [])[:8],
    }


def _compact_battle(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "battle_index": data.get("battle_index"),
        "won": data.get("won"),
        "opponent_name": data.get("opponent_name"),
        "matchup_score": data.get("matchup_score"),
        "outcome_summary": data.get("outcome_summary"),
        "reasons": list(data.get("reasons") or [])[:4],
    }


def _trim_by_role(session: ConversationState) -> None:
    """Оставить последние N user и N assistant, сохранив порядок."""
    users = [m for m in session.messages if m.role == "user"]
    assts = [m for m in session.messages if m.role == "assistant"]
    keep_u = set(id(m) for m in users[-MAX_USER_MESSAGES:])
    keep_a = set(id(m) for m in assts[-MAX_ASSISTANT_MESSAGES:])
    session.messages = [
        m
        for m in session.messages
        if (m.role == "user" and id(m) in keep_u)
        or (m.role == "assistant" and id(m) in keep_a)
    ]

    session.last_user_messages = [
        m.content for m in session.messages if m.role == "user"
    ][-MAX_USER_MESSAGES:]
    session.last_assistant_messages = [
        m.content for m in session.messages if m.role == "assistant"
    ][-MAX_ASSISTANT_MESSAGES:]
    session.last_questions = list(session.last_user_messages[-MAX_QUESTIONS:])


class ConversationManager:
    """Управление диалогом: сообщения, tools, summary, follow-up."""

    @staticmethod
    def get(telegram_id: int) -> ConversationState | None:
        return get_memory_provider().get(telegram_id)

    @staticmethod
    def get_or_create(telegram_id: int) -> ConversationState:
        return get_memory_provider().get_or_create(telegram_id)

    @staticmethod
    def save(telegram_id: int, session: ConversationState) -> None:
        get_memory_provider().save(telegram_id, session)

    @staticmethod
    def clear(telegram_id: int) -> None:
        get_memory_provider().clear(telegram_id)

    @staticmethod
    def clear_all() -> None:
        get_memory_provider().clear_all()

    @staticmethod
    def add_user_message(session: ConversationState, text: str) -> None:
        session.messages.append(
            ConversationMessage(role="user", content=text, ts=time.time())
        )
        session.last_questions.append(text)
        if len(session.last_questions) > MAX_QUESTIONS:
            session.last_questions = session.last_questions[-MAX_QUESTIONS:]
        _trim_by_role(session)
        maybe_compress(session)
        session.touch()

    @staticmethod
    def add_assistant_message(
        session: ConversationState,
        text: str,
        *,
        intent: str | None = None,
    ) -> None:
        # Проставить intent на последний user turn, если ещё пуст
        for m in reversed(session.messages):
            if m.role == "user":
                if not m.intent and intent:
                    m.intent = intent
                break
        session.messages.append(
            ConversationMessage(
                role="assistant",
                content=text,
                intent=intent,
                ts=time.time(),
            )
        )
        _trim_by_role(session)
        maybe_compress(session)
        session.touch()

    @staticmethod
    def record_tools(session: ConversationState, tools: list[str]) -> None:
        for name in tools:
            if not name:
                continue
            session.last_tools.append(name)
        if len(session.last_tools) > MAX_TOOLS:
            session.last_tools = session.last_tools[-MAX_TOOLS:]
        session.touch()

    @staticmethod
    def record_followup(
        session: ConversationState,
        *,
        kind: str,
        detail: str = "",
        intent: str | None = None,
    ) -> None:
        session.followups.append(
            FollowUpEvent(kind=kind, detail=detail, intent=intent)
        )
        if len(session.followups) > MAX_FOLLOWUPS:
            session.followups = session.followups[-MAX_FOLLOWUPS:]
        session.touch()

    @staticmethod
    def merge_request_context(
        session: ConversationState | None,
        request_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
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
        ctx["memory"] = session.memory_context()
        if session.last_replay and "replay" not in ctx:
            ctx["replay"] = dict(session.last_replay)
        return ctx

    @staticmethod
    def set_last_replay(session: ConversationState, meta: dict[str, Any]) -> None:
        from bot.services.ghosteek_ai.replay_followup import normalize_replay_meta

        normalized = normalize_replay_meta(meta)
        if normalized is None:
            session.last_replay = {}
            session.touch()
            return
        # Preserve Stage 6–7 coaching payload (normalize keeps detection fields only).
        for key in (
            "coach_reply",
            "coach_source",
            "has_analysis",
            "tactical_analysis",
            "confirmed_cards",
            "confirmed_events",
            "battle_timeline_summary",
        ):
            if key in meta:
                normalized[key] = meta[key]
        session.last_replay = dict(normalized)
        if normalized.get("accepted"):
            session.active_topic = "replay"
        session.touch()

    @staticmethod
    def apply_followup_enrichment(
        session: ConversationState,
        detected: Any,
        message: str,
        ctx: dict[str, Any],
    ) -> Any:
        intent = getattr(detected, "intent", None)
        cards = list(getattr(detected, "cards", None) or [])
        opponent = list(getattr(detected, "opponent_cards", None) or [])

        if intent in {"improve_deck", "analyze_deck", "matchup", "game_coach"}:
            if len(cards) < 8 and len(session.last_deck) >= 8:
                detected.cards = list(session.last_deck)
                ConversationManager.record_followup(
                    session,
                    kind="reuse_deck",
                    detail="last_deck",
                    intent=intent,
                )
            if intent == "matchup" and len(opponent) < 8:
                if len(session.last_opponent_deck) >= 8:
                    detected.opponent_cards = list(session.last_opponent_deck)
                    ConversationManager.record_followup(
                        session,
                        kind="reuse_opponent",
                        detail="last_opponent_deck",
                        intent=intent,
                    )

        if intent == "last_battle" and session.last_battle_index is not None:
            low = (message or "").lower()
            if any(
                k in low
                for k in ("этот бой", "тот бой", "ещё раз", "подробнее", "а что с боем")
            ):
                ctx["battle_index"] = session.last_battle_index
                ConversationManager.record_followup(
                    session,
                    kind="reuse_battle",
                    detail=str(session.last_battle_index),
                    intent=intent,
                )

        # Follow-up: «Как ею играть?» after build/analyze — reuse last deck.
        if intent == "clarify" and len(session.last_deck) >= 8:
            from bot.services.ghosteek_ai.intents import (
                INTENT_GAME_COACH,
                SERVICE_BY_INTENT,
                _is_how_to_play_request,
            )

            play_low = (message or "").lower().replace("ё", "е")
            if _is_how_to_play_request(play_low):
                detected.intent = INTENT_GAME_COACH
                detected.service = SERVICE_BY_INTENT.get(INTENT_GAME_COACH, "Game Coach")
                detected.cards = list(session.last_deck)
                detected.coach_topic = "how_to_play"
                ConversationManager.record_followup(
                    session,
                    kind="how_to_play_followup",
                    detail="last_deck",
                    intent=INTENT_GAME_COACH,
                )
                return detected

        # Follow-up: «ещё вариант / с этой комбинацией» — то же ядро, другой состав.
        from bot.services.ghosteek_ai.intents import (
            INTENT_BUILD_DECK,
            INTENT_IMPROVE_DECK,
            SERVICE_BY_INTENT,
            is_build_alternative_request,
            is_build_more_followup,
            parse_build_variant_count,
        )

        follow_low = (message or "").lower().replace("ё", "е")
        build_core = [c for c in (session.last_build_core or []) if isinstance(c, str)][:4]
        wants_alt = is_build_alternative_request(follow_low) or bool(
            getattr(detected, "prefer_alternative", False)
        )
        # «дай ещё» после сборки — тот же core, даже если intent ушёл в chat.
        if (
            not wants_alt
            and build_core
            and session.last_intent == INTENT_BUILD_DECK
            and is_build_more_followup(follow_low)
        ):
            wants_alt = True
        if wants_alt and build_core:
            core_cards = cards[:4] if cards else build_core
            # Карты из сообщения дополняют/заменяют ядро только если явно названы.
            if cards and not set(cards).issubset(set(build_core) | set(session.last_deck or [])):
                # Новые карты в запросе — собираем вокруг них.
                core_cards = cards[:4]
            else:
                core_cards = build_core
            detected.intent = INTENT_BUILD_DECK
            detected.service = SERVICE_BY_INTENT.get(INTENT_BUILD_DECK, "Builder")
            detected.cards = list(core_cards)[:4]
            detected.prefer_alternative = True
            count = parse_build_variant_count(follow_low) or getattr(detected, "build_limit", None) or 1
            detected.build_limit = max(1, min(3, int(count)))
            ctx["exclude_decks"] = [list(d) for d in (session.last_build_shown or []) if d]
            if session.last_deck and len(session.last_deck) >= 8:
                ctx.setdefault("exclude_decks", []).append(list(session.last_deck)[:8])
            ctx["build_limit"] = detected.build_limit
            ctx["prefer_alternative"] = True
            ConversationManager.record_followup(
                session,
                kind="build_alternative",
                detail=",".join(detected.cards),
                intent=INTENT_BUILD_DECK,
            )
            return detected

        # build_deck без карт, но ядро в сессии — добираем ядро (в т.ч. «2 колоды» после сборки).
        if intent == INTENT_BUILD_DECK and not cards and build_core:
            detected.cards = list(build_core)[:4]
            count = parse_build_variant_count(follow_low) or getattr(detected, "build_limit", None)
            if count:
                detected.build_limit = max(1, min(3, int(count)))
                ctx["build_limit"] = detected.build_limit
            if wants_alt or getattr(detected, "prefer_alternative", False):
                detected.prefer_alternative = True
                ctx["prefer_alternative"] = True
                ctx["exclude_decks"] = [list(d) for d in (session.last_build_shown or []) if d]
                if session.last_deck and len(session.last_deck) >= 8:
                    ctx.setdefault("exclude_decks", []).append(list(session.last_deck)[:8])
            ConversationManager.record_followup(
                session,
                kind="build_reuse_core",
                detail=",".join(detected.cards),
                intent=INTENT_BUILD_DECK,
            )
            return detected

        # Follow-up: «а что заменить / медленная / оставить карту» при clarify + last_deck.
        if intent == "clarify" and len(session.last_deck) >= 8:
            if follow_low.startswith("а почему") or follow_low in {
                "почему",
                "почему?",
                "а почему?",
            }:
                ConversationManager.record_followup(
                    session,
                    kind="why_followup",
                    detail="await_facts_reuse",
                    intent=session.last_intent or "clarify",
                )
                return detected
            improve_keys = (
                "замен",
                "помен",
                "вместо",
                "медлен",
                "тормоз",
                "тяжел",
                "улучш",
                "что тут",
            )
            keep_keys = ("оста", "оставить", "можно оставить")
            if any(k in follow_low for k in improve_keys):
                detected.intent = INTENT_IMPROVE_DECK
                detected.service = SERVICE_BY_INTENT.get(
                    INTENT_IMPROVE_DECK, "Recommendation"
                )
                detected.cards = list(session.last_deck)
                ConversationManager.record_followup(
                    session,
                    kind="improve_followup",
                    detail="last_deck",
                    intent=INTENT_IMPROVE_DECK,
                )
                return detected
            if any(k in follow_low for k in keep_keys) and (
                cards or session.last_intent == INTENT_BUILD_DECK
            ):
                keep = cards[:4] if cards else []
                detected.intent = INTENT_BUILD_DECK
                detected.service = SERVICE_BY_INTENT.get(INTENT_BUILD_DECK, "Deck Builder")
                detected.cards = keep or list(session.last_deck)[:4]
                ConversationManager.record_followup(
                    session,
                    kind="keep_card_rebuild",
                    detail=",".join(detected.cards),
                    intent=INTENT_BUILD_DECK,
                )
                return detected

        # Follow-up: после «собери колоду?» бот просит карту → игрок пишет только имя карты.
        if intent == "clarify" and cards and session.last_intent == "build_deck":
            from bot.services.ghosteek_ai.intents import (
                INTENT_BUILD_DECK,
                SERVICE_BY_INTENT,
            )

            words = [w for w in (message or "").split() if w.strip()]
            if len(words) <= 8 and len(cards) <= 4:
                detected.intent = INTENT_BUILD_DECK
                detected.service = SERVICE_BY_INTENT.get(INTENT_BUILD_DECK, "Deck Builder")
                detected.cards = cards[:4]
                ConversationManager.record_followup(
                    session,
                    kind="build_card_followup",
                    detail=",".join(cards[:4]),
                    intent=INTENT_BUILD_DECK,
                )
                return detected

        # Follow-up по местоимениям: «а это?», «подробнее» при clarify → reuse last topic
        low = (message or "").lower().strip()
        if intent == "clarify" and session.active_topic and session.last_questions:
            if any(
                k in low
                for k in ("а это", "подробнее", "ещё", "а что насчёт", "продолж", "и что")
            ):
                ConversationManager.record_followup(
                    session,
                    kind="pronoun_followup",
                    detail=session.active_topic,
                    intent=session.last_intent,
                )

        return detected

    @staticmethod
    def update_from_ai_context(
        session: ConversationState,
        *,
        intent: str,
        service: str | None,
        data: dict[str, Any],
        ok: bool,
        active_topic: str | None = None,
        tools: list[str] | None = None,
    ) -> None:
        session.last_intent = intent
        session.last_service = service
        if active_topic is not None:
            session.active_topic = active_topic
        elif intent and intent != "chat":
            session.active_topic = intent

        if tools:
            ConversationManager.record_tools(session, tools)

        session.touch()

        if not ok and not data:
            return

        deck = data.get("deck")
        if intent in {"improve_deck", "recommendation"}:
            original = data.get("original_deck")
            if isinstance(original, list) and len(original) >= 8:
                deck = original
        if isinstance(deck, list) and len(deck) >= 8:
            session.last_deck = [c for c in deck if isinstance(c, str)][:8]

        user_deck = data.get("user_deck")
        if isinstance(user_deck, list) and len(user_deck) >= 8:
            session.last_deck = [c for c in user_deck if isinstance(c, str)][:8]

        if intent == "build_deck":
            core_raw = data.get("core")
            if isinstance(core_raw, list) and core_raw:
                session.last_build_core = [c for c in core_raw if isinstance(c, str)][:4]
            decks = data.get("decks") or []
            shown: list[list[str]] = list(session.last_build_shown or [])
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
            for entry in decks if isinstance(decks, list) else []:
                if not isinstance(entry, dict):
                    continue
                cards = entry.get("cards") or []
                names = []
                if isinstance(cards, list):
                    for c in cards:
                        if isinstance(c, str):
                            names.append(c)
                        elif isinstance(c, dict) and c.get("name"):
                            names.append(str(c["name"]))
                if len(names) >= 8:
                    key = "|".join(sorted(names[:8]))
                    if key not in {"|".join(sorted(d)) for d in shown if len(d) >= 8}:
                        shown.append(names[:8])
            session.last_build_shown = shown[-8:]

        opp = data.get("opponent_deck")
        if isinstance(opp, list) and len(opp) >= 8:
            session.last_opponent_deck = [c for c in opp if isinstance(c, str)][:8]

        if data.get("battle_index") is not None:
            try:
                session.last_battle_index = int(data["battle_index"])
            except (TypeError, ValueError):
                pass

        if intent == "last_battle" and data:
            session.last_battle = _compact_battle(data)

        if intent in {"analyze_deck", "improve_deck"} and data:
            session.last_recommendation = _compact_recommendation(data)

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


# --- Совместимость со старым session_context API ---

def get_session(telegram_id: int) -> ConversationState | None:
    return ConversationManager.get(telegram_id)


def get_or_create_session(telegram_id: int) -> ConversationState:
    return ConversationManager.get_or_create(telegram_id)


def clear_session(telegram_id: int) -> None:
    ConversationManager.clear(telegram_id)


def clear_all_sessions() -> None:
    ConversationManager.clear_all()


def merge_request_context(
    session: ConversationState | None,
    request_context: dict[str, Any] | None,
) -> dict[str, Any]:
    return ConversationManager.merge_request_context(session, request_context)


def update_session_from_payload(
    session: ConversationState,
    *,
    intent: str,
    service: str | None,
    payload: dict[str, Any],
) -> None:
    ConversationManager.update_from_ai_context(
        session,
        intent=intent,
        service=service,
        data=payload.get("data") or {},
        ok=bool(payload.get("ok")),
    )


__all__ = [
    "SESSION_TTL_SECONDS",
    "AiSessionContext",
    "ConversationManager",
    "ConversationState",
    "clear_all_sessions",
    "clear_session",
    "get_or_create_session",
    "get_session",
    "merge_request_context",
    "update_session_from_payload",
]
