"""Tool: Deck Builder — constructor / meta templates."""

from __future__ import annotations

from bot.services.card_names_ru import card_name_ru
from bot.services.deck_constructor import build_constructor_decks
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.game_coach import decks_for_win_condition
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema


class DeckBuilderTool(BaseTool):
    name = "deck_builder"
    description = (
        "Build decks from a win-condition card or a 4-card core "
        "(constructor or curated meta templates). Returns deck lists only."
    )
    input_schema = object_schema({"cards": COMMON_INPUT_PROPERTIES["cards"]})

    async def execute(self, ctx: AIContext) -> ToolResult:
        user = ctx.require_user()
        core = ctx.cards_arg()

        if len(core) >= 4:
            slots = [{"name": n, "slot": i} for i, n in enumerate(core[:4])]
            result = build_constructor_decks(
                slots,
                arena_id=ctx.arena.arena_id,
                trophies=ctx.arena.trophies,
                limit=3,
            )
            decks = result.get("decks") or []
            if not decks:
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    error_code="BUILD_NO_VARIANTS",
                    data={"core": core[:4]},
                    actions=[{"type": "navigate", "path": "/decks"}],
                )
            return ToolResult(
                tool=self.name,
                ok=True,
                data={"core": core[:4], "decks": decks[:3], "mode": "constructor"},
                actions=[{"type": "navigate", "path": "/decks"}],
            )

        if len(core) >= 1:
            templates: list[dict] = []
            seen: set[str] = set()
            for card in core:
                for d in decks_for_win_condition(card, limit=3):
                    key = d.get("key") or d.get("name")
                    if key in seen:
                        continue
                    seen.add(str(key))
                    templates.append(d)
                if len(templates) >= 3:
                    break
            if templates:
                return ToolResult(
                    tool=self.name,
                    ok=True,
                    data={
                        "core": core,
                        "decks": templates[:3],
                        "mode": "meta_templates",
                    },
                    actions=[{"type": "navigate", "path": "/decks"}],
                )
            return ToolResult(
                tool=self.name,
                ok=False,
                error_code="BUILD_NO_TEMPLATES",
                error_params={"card_ru": card_name_ru(core[0])},
                data={"core": core},
                actions=[{"type": "navigate", "path": "/decks"}],
            )

        del user
        return ToolResult(
            tool=self.name,
            ok=False,
            error_code="BUILD_NEED_CORE",
            actions=[{"type": "navigate", "path": "/decks"}],
        )
