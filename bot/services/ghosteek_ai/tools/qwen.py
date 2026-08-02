"""Qwen Tool Calling bridge — tools работают через AIContext."""

from __future__ import annotations

from typing import Any

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import ToolCaller, ToolRegistry, get_default_registry


def export_qwen_tools(registry: ToolRegistry | None = None) -> list[dict[str, Any]]:
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


def format_tool_results_for_llm(results: list[ToolResult]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        out.append(
            {
                "role": "tool",
                "name": r.tool,
                "tool_call_id": f"call_{i}",
                "content": r.to_dict(),
            }
        )
    return out
