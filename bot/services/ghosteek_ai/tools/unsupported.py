"""Tool: unsupported request."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.schema import object_schema


class UnsupportedTool(BaseTool):
    name = "unsupported"
    description = (
        "Refuse requests that need data we do not have "
        "(replay frames, exact damage, elixir in hand, card play counts)."
    )
    input_schema = object_schema(
        {"raw": {"type": "string", "description": "Original user message"}},
    )

    async def execute(self, ctx: AIContext) -> ToolResult:
        del ctx
        return ToolResult(tool=self.name, ok=False, error_code="UNSUPPORTED")
