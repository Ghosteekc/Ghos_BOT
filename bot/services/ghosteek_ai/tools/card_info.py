"""Tool: Card Info — structured card profile."""

from __future__ import annotations

from bot.services.card_names_ru import card_name_ru
from bot.services.card_profile import get_card_profile
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema


class CardInfoTool(BaseTool):
    name = "card_info"
    description = (
        "Return structured Clash Royale card profile: elixir, type, roles. "
        "No invented damage or HP numbers."
    )
    input_schema = object_schema(
        {
            "card_query": COMMON_INPUT_PROPERTIES["card_query"],
            "cards": COMMON_INPUT_PROPERTIES["cards"],
        },
    )

    async def execute(self, ctx: AIContext) -> ToolResult:
        name = ctx.intent.card_query or ctx.arg("card_query")
        if not name:
            cards = ctx.cards_arg()
            name = cards[0] if cards else None
        if not name or not isinstance(name, str):
            return ToolResult(tool=self.name, ok=False, error_code="NEED_CARD_NAME")
        profile = get_card_profile(name)
        return ToolResult(
            tool=self.name,
            ok=True,
            data={
                "name": name,
                "name_ru": card_name_ru(name),
                "elixir": profile.elixir,
                "card_type": profile.card_type,
                "roles": sorted(profile.roles),
            },
        )
