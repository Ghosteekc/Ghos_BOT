"""Общие модели Ghosteek AI Orchestrator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Версия envelope ToolResult (дублирует tools.schema.TOOL_RESULT_SCHEMA_VERSION —
# models не импортирует tools.*, чтобы избежать circular import).
TOOL_RESULT_SCHEMA_VERSION = "1"

@dataclass
class ConversationMessage:
    role: str  # "user" | "assistant"
    content: str
    intent: str | None = None
    ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "intent": self.intent,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ConversationMessage":
        return cls(
            role=str(raw.get("role") or "user"),
            content=str(raw.get("content") or ""),
            intent=raw.get("intent"),
            ts=float(raw.get("ts") or 0.0),
        )


@dataclass
class FollowUpEvent:
    """Событие follow-up в рамках сессии (для истории и отладки)."""

    kind: str
    detail: str = ""
    intent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, "intent": self.intent}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FollowUpEvent":
        return cls(
            kind=str(raw.get("kind") or ""),
            detail=str(raw.get("detail") or ""),
            intent=raw.get("intent"),
        )


@dataclass
class ToolSpec:
    """План: какой tool вызвать и с какими аргументами (без текста)."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "args": dict(self.args)}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ToolSpec":
        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        return cls(name=str(raw.get("name") or ""), args=dict(args))


@dataclass
class Plan:
    """Результат Planner — только выбор инструментов."""

    intent: str
    service: str
    tools: list[ToolSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "service": self.service,
            "tools": [t.to_dict() for t in self.tools],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Plan":
        tools_raw = raw.get("tools") if isinstance(raw.get("tools"), list) else []
        return cls(
            intent=str(raw.get("intent") or ""),
            service=str(raw.get("service") or ""),
            tools=[
                ToolSpec.from_dict(t) if isinstance(t, dict) else ToolSpec(name=str(t))
                for t in tools_raw
            ],
        )


@dataclass
class ToolRequest:
    """Вход для Tool Layer."""

    args: dict[str, Any]
    context: dict[str, Any]
    session_public: dict[str, Any]
    user_telegram_id: int
    player_tag: str | None = None
    arena_id: int | None = None
    trophies: int | None = None
    raw_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "args": dict(self.args),
            "context": dict(self.context),
            "session_public": dict(self.session_public),
            "user_telegram_id": self.user_telegram_id,
            "player_tag": self.player_tag,
            "arena_id": self.arena_id,
            "trophies": self.trophies,
            "raw_message": self.raw_message,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ToolRequest":
        return cls(
            args=dict(raw.get("args") or {}) if isinstance(raw.get("args"), dict) else {},
            context=dict(raw.get("context") or {})
            if isinstance(raw.get("context"), dict)
            else {},
            session_public=dict(raw.get("session_public") or {})
            if isinstance(raw.get("session_public"), dict)
            else {},
            user_telegram_id=int(raw.get("user_telegram_id") or 0),
            player_tag=raw.get("player_tag"),
            arena_id=raw.get("arena_id"),
            trophies=raw.get("trophies"),
            raw_message=str(raw.get("raw_message") or ""),
        )


@dataclass
class ToolResult:
    """Стандартизированный выход Tool — structured data, без текста игроку.

    Соответствует STANDARD_OUTPUT_SCHEMA.
    """

    tool: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_params: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, str]] = field(default_factory=list)
    call_id: str = ""
    schema_version: str = TOOL_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "data": dict(self.data) if isinstance(self.data, dict) else {},
            "error_code": self.error_code,
            "error_params": dict(self.error_params)
            if isinstance(self.error_params, dict)
            else {},
            "actions": [dict(a) for a in self.actions if isinstance(a, dict)],
            "call_id": self.call_id,
            "schema_version": self.schema_version or TOOL_RESULT_SCHEMA_VERSION,
        }

    def to_llm_content(self) -> str:
        """JSON-строка для role=tool content в Chat Completions / Qwen."""
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ToolResult":
        data = raw.get("data")
        error_params = raw.get("error_params")
        actions = raw.get("actions")
        return cls(
            tool=str(raw.get("tool") or ""),
            ok=bool(raw.get("ok")),
            data=dict(data) if isinstance(data, dict) else {},
            error_code=raw.get("error_code"),
            error_params=dict(error_params) if isinstance(error_params, dict) else {},
            actions=[dict(a) for a in actions if isinstance(a, dict)]
            if isinstance(actions, list)
            else [],
            call_id=str(raw.get("call_id") or ""),
            schema_version=str(raw.get("schema_version") or TOOL_RESULT_SCHEMA_VERSION),
        )

    def normalized(self, *, call_id: str | None = None) -> "ToolResult":
        """Гарантировать стандартный envelope (idempotent)."""
        actions: list[dict[str, str]] = []
        for item in self.actions or []:
            if not isinstance(item, dict):
                continue
            actions.append(
                {
                    "type": str(item.get("type") or "navigate"),
                    "path": str(item.get("path") or "/"),
                }
            )
        return ToolResult(
            tool=str(self.tool or ""),
            ok=bool(self.ok),
            data=dict(self.data) if isinstance(self.data, dict) else {},
            error_code=self.error_code,
            error_params=dict(self.error_params)
            if isinstance(self.error_params, dict)
            else {},
            actions=actions,
            call_id=str(call_id if call_id is not None else self.call_id or ""),
            schema_version=self.schema_version or TOOL_RESULT_SCHEMA_VERSION,
        )


# Единый AIContext живёт в context/ai_context.py
from bot.services.ghosteek_ai.context.ai_context import AIContext  # noqa: E402


@dataclass
class GhosteekAiAction:
    type: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "path": self.path}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GhosteekAiAction":
        return cls(type=str(raw.get("type") or "navigate"), path=str(raw.get("path") or "/"))


@dataclass
class GhosteekAiResponse:
    intent: str
    answer: str
    sources: dict[str, Any] = field(default_factory=dict)
    actions: list[GhosteekAiAction] = field(default_factory=list)
    deck_card: dict[str, Any] | None = None
    deck_cards: list[dict[str, Any]] = field(default_factory=list)
    battle_card: dict[str, Any] | None = None
    analysis_card: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "answer": self.answer,
            "sources": self.sources,
            "actions": [a.to_dict() if hasattr(a, "to_dict") else asdict(a) for a in self.actions],
            "deck_card": self.deck_card,
            "deck_cards": list(self.deck_cards),
            "battle_card": self.battle_card,
            "analysis_card": self.analysis_card,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GhosteekAiResponse":
        actions_raw = raw.get("actions") if isinstance(raw.get("actions"), list) else []
        deck_card = raw.get("deck_card") if isinstance(raw.get("deck_card"), dict) else None
        deck_cards_raw = raw.get("deck_cards") if isinstance(raw.get("deck_cards"), list) else []
        deck_cards = [dict(c) for c in deck_cards_raw if isinstance(c, dict)]
        battle_card = raw.get("battle_card") if isinstance(raw.get("battle_card"), dict) else None
        analysis_card = (
            raw.get("analysis_card") if isinstance(raw.get("analysis_card"), dict) else None
        )
        return cls(
            intent=str(raw.get("intent") or ""),
            answer=str(raw.get("answer") or ""),
            sources=dict(raw.get("sources") or {})
            if isinstance(raw.get("sources"), dict)
            else {},
            actions=[
                GhosteekAiAction.from_dict(a) if isinstance(a, dict) else GhosteekAiAction("navigate", "/")
                for a in actions_raw
            ],
            deck_card=dict(deck_card) if deck_card else None,
            deck_cards=deck_cards,
            battle_card=dict(battle_card) if battle_card else None,
            analysis_card=dict(analysis_card) if analysis_card else None,
        )
