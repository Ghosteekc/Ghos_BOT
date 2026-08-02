"""Tool: Knowledge / Mechanics — structured dictionary lookup."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.knowledge_base import (
    format_mechanic_answer,
    list_mechanic_titles,
    lookup_mechanic,
)
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema


_KNOWLEDGE_INPUT = object_schema(
    {
        "mechanic_query": COMMON_INPUT_PROPERTIES["mechanic_query"],
        "raw": COMMON_INPUT_PROPERTIES["raw"],
    },
)


class KnowledgeTool(BaseTool):
    name = "knowledge"
    description = (
        "Explain a Clash Royale mechanic/term from the curated knowledge base "
        "(Cycle, Tempo, Overcommit, etc.). Returns structured fields only."
    )
    input_schema = _KNOWLEDGE_INPUT

    async def execute(self, ctx: AIContext) -> ToolResult:
        key = ctx.intent.mechanic_query or ctx.arg("mechanic_query")
        entry = lookup_mechanic(key if isinstance(key, str) else None)
        if entry is None:
            return ToolResult(
                tool=self.name,
                ok=False,
                error_code="UNKNOWN_MECHANIC",
                error_params={"suggestions": list_mechanic_titles(limit=8)},
            )
        return ToolResult(
            tool=self.name,
            ok=True,
            data={
                "key": entry.key,
                "title": entry.title,
                "summary": entry.summary,
                "example": entry.example,
                "tip": entry.tip,
                "answer": format_mechanic_answer(entry),
            },
        )


class MechanicsTool(KnowledgeTool):
    name = "mechanics"
    description = (
        "Alias of knowledge: explain a Clash Royale mechanic from the dictionary."
    )
