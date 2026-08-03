"""Схемы и определения Tool — совместимы с Qwen / OpenAI function calling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- Переиспользуемые фрагменты JSON Schema ---

SCHEMA_CARDS: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string"},
    "description": "English card names (Clash Royale), 0–8 items",
}

SCHEMA_OPPONENT_CARDS: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Opponent deck card names, 0–8 items",
}

COMMON_INPUT_PROPERTIES: dict[str, Any] = {
    "cards": SCHEMA_CARDS,
    "opponent_cards": SCHEMA_OPPONENT_CARDS,
    "card_query": {
        "type": "string",
        "description": "Single card name to look up",
    },
    "mechanic_query": {
        "type": "string",
        "description": "Mechanic key, e.g. cycle, tempo, overcommit",
    },
    "coach_topic": {
        "type": "string",
        "enum": ["climb", "vs_advice", "general"],
        "description": "Game coach topic",
    },
    "raw": {
        "type": "string",
        "description": "Original user message (for archetype alias matching)",
    },
    "battle_index": {
        "type": "integer",
        "minimum": 0,
        "description": "Index in recent battles list",
    },
}

# Единый envelope ToolResult (все tools обязаны соответствовать)
STANDARD_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tool", "ok", "data", "schema_version"],
    "additionalProperties": False,
    "properties": {
        "tool": {
            "type": "string",
            "description": "Registered tool name",
        },
        "ok": {"type": "boolean"},
        "data": {
            "type": "object",
            "description": "Structured tool payload (no player-facing prose required)",
        },
        "error_code": {
            "type": ["string", "null"],
            "description": "Machine error code for Response Generator",
        },
        "error_params": {"type": "object"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "path"],
                "properties": {
                    "type": {"type": "string"},
                    "path": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "call_id": {
            "type": "string",
            "description": "tool_call_id from Planner / Qwen tool_calls[]",
        },
        "schema_version": {
            "type": "string",
            "description": "ToolResult schema version",
        },
    },
}

TOOL_RESULT_SCHEMA_VERSION = "1"  # keep in sync with models.TOOL_RESULT_SCHEMA_VERSION


def object_schema(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    if description:
        schema["description"] = description
    return schema


def is_valid_json_schema_object(schema: dict[str, Any] | None) -> bool:
    """Минимальная проверка, что у tool есть JSON Schema object."""
    if not isinstance(schema, dict):
        return False
    if schema.get("type") != "object":
        return False
    props = schema.get("properties")
    return isinstance(props, dict)


@dataclass(frozen=True)
class ToolDefinition:
    """Публичное описание tool без реализации (для Planner / Qwen)."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = field(default_factory=lambda: dict(STANDARD_OUTPUT_SCHEMA))

    def to_openai_tool(self) -> dict[str, Any]:
        """OpenAI Chat Completions tools[] format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def to_qwen_function(self) -> dict[str, Any]:
        """Qwen / DashScope tool-calling function entry.

        Compatible with OpenAI-style tools; Qwen accepts the same shape
        when using function calling / tools API.
        """
        return self.to_openai_tool()

    def to_catalog_entry(self) -> dict[str, Any]:
        """Внутренний каталог: name + schemas (Planner / docs / LLM)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "parameters": self.input_schema,  # alias for LLM SDKs
        }


@dataclass
class ToolCall:
    """Один вызов tool — от Planner или от Qwen tool_calls[]."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    @classmethod
    def from_qwen_tool_call(cls, raw: dict[str, Any]) -> "ToolCall":
        """Парсинг элемента tool_calls из ответа Qwen/OpenAI."""
        fn = raw.get("function") if isinstance(raw.get("function"), dict) else raw
        name = str(fn.get("name") or raw.get("name") or "")
        args = fn.get("arguments") if isinstance(fn, dict) else raw.get("arguments")
        parsed: dict[str, Any] = {}
        if isinstance(args, dict):
            parsed = dict(args)
        elif isinstance(args, str) and args.strip():
            import json

            try:
                loaded = json.loads(args)
                if isinstance(loaded, dict):
                    parsed = loaded
            except json.JSONDecodeError:
                parsed = {}
        return cls(name=name, arguments=parsed, id=str(raw.get("id") or ""))

    def to_spec_args(self) -> dict[str, Any]:
        return dict(self.arguments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": dict(self.arguments),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ToolCall":
        return cls(
            name=str(raw.get("name") or ""),
            arguments=dict(raw.get("arguments") or {})
            if isinstance(raw.get("arguments"), dict)
            else {},
            id=str(raw.get("id") or ""),
        )
