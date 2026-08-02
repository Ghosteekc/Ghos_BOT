"""Tool: Meta — stage-1 stub."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.schema import object_schema


class MetaTool(BaseTool):
    name = "meta"
    description = (
        "Live / curated meta decks snapshot. "
        "Not wired in stage-1; returns META_NOT_READY."
    )
    input_schema = object_schema({"raw": {"type": "string"}})

    async def execute(self, ctx: AIContext) -> ToolResult:
        del ctx
        return ToolResult(tool=self.name, ok=False, error_code="META_NOT_READY")
