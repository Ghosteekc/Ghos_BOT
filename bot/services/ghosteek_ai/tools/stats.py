"""Tool: Stats — stage-1 stub."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.schema import object_schema


class StatsTool(BaseTool):
    name = "stats"
    description = (
        "Player statistics snapshot. "
        "Not wired in stage-1; returns STATS_NOT_READY."
    )
    input_schema = object_schema({"raw": {"type": "string"}})

    async def execute(self, ctx: AIContext) -> ToolResult:
        del ctx
        return ToolResult(tool=self.name, ok=False, error_code="STATS_NOT_READY")
