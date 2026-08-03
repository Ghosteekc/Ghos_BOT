"""Qwen Tool Calling bridge — tools работают через AIContext.

Модель не вызывается. Экспорт schemas + исполнение tool_calls + format для LLM.
"""

from __future__ import annotations

import json
from typing import Any

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import ToolCaller, ToolRegistry, get_default_registry


def export_qwen_tools(registry: ToolRegistry | None = None) -> list[dict[str, Any]]:
    """tools[] для Qwen / OpenAI function calling (JSON Schema parameters)."""
    reg = registry or get_default_registry()
    return reg.qwen_tools()


def export_tool_catalog(registry: ToolRegistry | None = None) -> list[dict[str, Any]]:
    reg = registry or get_default_registry()
    return reg.catalog()


async def run_qwen_tool_calls(
    raw_tool_calls: list[dict[str, Any]],
    *,
    ctx: AIContext,
    registry: ToolRegistry | None = None,
) -> list[ToolResult]:
    """Выполнить tool_calls из ответа Qwen → обновляет AIContext + ToolResult[]."""
    caller = ToolCaller(registry or get_default_registry())
    return await caller.execute_qwen_tool_calls(raw_tool_calls, ctx)


def format_tool_results_for_llm(
    results: list[ToolResult],
    *,
    call_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Сообщения role=tool для Chat Completions / Qwen.

    content — JSON-строка стандартизированного ToolResult.to_dict().
    """
    out: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        normalized = r.normalized()
        call_id = ""
        if call_ids and i < len(call_ids) and call_ids[i]:
            call_id = call_ids[i]
        elif normalized.call_id:
            call_id = normalized.call_id
        else:
            call_id = f"call_{i}"
        payload = normalized.normalized(call_id=call_id)
        out.append(
            {
                "role": "tool",
                "name": payload.tool,
                "tool_call_id": call_id,
                "content": payload.to_llm_content(),
            }
        )
    return out


def tool_results_to_jsonable(results: list[ToolResult]) -> list[dict[str, Any]]:
    return [r.normalized().to_dict() for r in results]


def dumps_tool_results(results: list[ToolResult]) -> str:
    return json.dumps(tool_results_to_jsonable(results), ensure_ascii=False)
