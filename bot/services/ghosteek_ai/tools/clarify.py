"""Tool: clarify — недостаточно сигнала."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema


class ClarifyTool(BaseTool):
    name = "clarify"
    description = (
        "Ask the player to clarify when the request is ambiguous. "
        "Does not guess intent."
    )
    input_schema = object_schema(
        {k: COMMON_INPUT_PROPERTIES[k] for k in ("cards", "raw")},
    )

    async def execute(self, ctx: AIContext) -> ToolResult:
        del ctx
        return ToolResult(tool=self.name, ok=False, error_code="CLARIFY")
