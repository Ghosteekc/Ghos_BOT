"""LLM message types for Ghosteek AI."""

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
    tool_calls: list[dict[str, Any]] | None = None
    # Groq reasoning models: round-trip поля reasoning в multi-turn
    reasoning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        role = self.role.value if isinstance(self.role, MessageRole) else str(self.role)
        out: dict[str, Any] = {"role": role, "content": self.content}
        if self.name:
            out["name"] = self.name
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            out["tool_calls"] = list(self.tool_calls)
        if self.reasoning:
            out["reasoning"] = self.reasoning
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChatMessage":
        role_raw = str(raw.get("role") or MessageRole.USER.value)
        try:
            role: MessageRole | str = MessageRole(role_raw)
        except ValueError:
            role = role_raw
        tool_calls = raw.get("tool_calls")
        reasoning = raw.get("reasoning") or raw.get("reasoning_content")
        return cls(
            role=role,
            content=str(raw.get("content") or ""),
            name=raw.get("name"),
            tool_call_id=raw.get("tool_call_id"),
            tool_calls=[dict(t) for t in tool_calls if isinstance(t, dict)]
            if isinstance(tool_calls, list)
            else None,
            reasoning=str(reasoning) if reasoning else None,
        )


@dataclass
class LLMToolCall:
    """Один tool_call из ответа модели (структура, без исполнения)."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        import json

        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False)
                if isinstance(self.arguments, dict)
                else self.arguments,
            },
        }

    def to_openai_dict(self) -> dict[str, Any]:
        return self.to_dict()


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
    """Нормализованный ответ провайдера (текст и/или tool_calls / reasoning)."""

    text: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    reasoning: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "reasoning": self.reasoning,
            "raw": dict(self.raw),
            "finish_reason": self.finish_reason,
            "model": self.model,
        }

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def has_usable_output(self) -> bool:
        return bool((self.text or "").strip() or self.has_tool_calls or (self.reasoning or "").strip())


@dataclass
class ToolCallResult:
    """Модель запросила tools — не финальный текст пользователю.

    Возвращается из QwenResponseGenerator вместо ответа игроку.
    Исполнение — через существующий ToolCaller / execute_llm_round.
    """

    tool_calls: list[LLMToolCall] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)
    raw: LLMGenerateResult | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "messages": [m.to_dict() for m in self.messages],
            "raw": self.raw.to_dict() if self.raw is not None else None,
        }

    def to_openai_tool_calls(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.tool_calls]


def messages_to_openai(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [m.to_dict() for m in messages]


def dump_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [m.to_dict() for m in messages]
