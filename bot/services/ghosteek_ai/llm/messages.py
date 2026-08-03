"""LLM message types for Ghosteek AI (no model calls)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ChatMessage:
    """Одно сообщение в chat-completions формате."""

    role: MessageRole | str
    content: str
    name: str | None = None
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        role = self.role.value if isinstance(self.role, MessageRole) else str(self.role)
        out: dict[str, Any] = {"role": role, "content": self.content}
        if self.name:
            out["name"] = self.name
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChatMessage":
        role_raw = str(raw.get("role") or MessageRole.USER.value)
        try:
            role: MessageRole | str = MessageRole(role_raw)
        except ValueError:
            role = role_raw
        return cls(
            role=role,
            content=str(raw.get("content") or ""),
            name=raw.get("name"),
            tool_call_id=raw.get("tool_call_id"),
        )


@dataclass
class LLMToolCall:
    """Один tool_call из ответа модели (структура, без исполнения)."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass
class LLMGenerateRequest:
    """Вход в LLMProvider.generate / stream_generate."""

    messages: list[ChatMessage]
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": [m.to_dict() for m in self.messages],
            "tools": list(self.tools) if self.tools else None,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "model": self.model,
            "extra": dict(self.extra),
        }


@dataclass
class LLMGenerateResult:
    """Нормализованный ответ провайдера (текст и/или tool_calls)."""

    text: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "raw": dict(self.raw),
            "finish_reason": self.finish_reason,
            "model": self.model,
        }

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


def messages_to_openai(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [m.to_dict() for m in messages]


def dump_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [m.to_dict() for m in messages]
