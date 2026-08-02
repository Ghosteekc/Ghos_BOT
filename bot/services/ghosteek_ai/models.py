"""Общие модели Ghosteek AI Orchestrator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ConversationMessage:
    role: str  # "user" | "assistant"
    content: str
    intent: str | None = None
    ts: float = 0.0


@dataclass
class FollowUpEvent:
    """Событие follow-up в рамках сессии (для истории и отладки)."""

    kind: str
    detail: str = ""
    intent: str | None = None


@dataclass
class ToolSpec:
    """План: какой tool вызвать и с какими аргументами (без текста)."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    """Результат Planner — только выбор инструментов."""

    intent: str
    service: str
    tools: list[ToolSpec] = field(default_factory=list)


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


@dataclass
class ToolResult:
    """Выход Tool — только structured data, без текста игроку."""

    tool: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_params: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "data": self.data,
            "error_code": self.error_code,
            "error_params": self.error_params,
            "actions": list(self.actions),
        }


# Единый AIContext живёт в context/ai_context.py
from bot.services.ghosteek_ai.context.ai_context import AIContext  # noqa: E402


@dataclass
class GhosteekAiAction:
    type: str
    path: str


@dataclass
class GhosteekAiResponse:
    intent: str
    answer: str
    sources: dict[str, Any] = field(default_factory=dict)
    actions: list[GhosteekAiAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "answer": self.answer,
            "sources": self.sources,
            "actions": [asdict(a) for a in self.actions],
        }
