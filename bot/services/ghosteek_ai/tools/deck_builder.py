"""Tool: Deck Builder — constructor / meta templates."""

from __future__ import annotations

from bot.services.card_names_ru import card_name_ru
from bot.services.deck_constructor import build_constructor_decks
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.deck_card import deck_card_from_entry, format_arena_label
from bot.services.ghosteek_ai.game_coach import decks_for_win_condition
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema


class DeckBuilderTool(BaseTool):
    name = "deck_builder"
    description = (
        "Build decks from a win-condition card or a 4-card core "
        "(constructor or curated meta templates). "
        "Returns structured deck_card for UI — do not list cards in text."
    )
    input_schema = object_schema({"cards": COMMON_INPUT_PROPERTIES["cards"]})

    async def execute(self, ctx: AIContext) -> ToolResult:
        user = ctx.require_user()
        core = ctx.cards_arg()
        arena_label = format_arena_label(ctx.arena.arena_id, ctx.arena.trophies)

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
            deck_card = deck_card_from_entry(decks[0], arena=arena_label)
            data: dict = {"core": core[:4], "decks": decks[:3], "mode": "constructor"}
            if deck_card:
                data["deck_card"] = deck_card
                ctx.deck_card = deck_card
            return ToolResult(
                tool=self.name,
                ok=True,
                data=data,
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
                from bot.services.deck_sanity_validator import validate_deck_sanity
                from bot.services.ghosteek_ai.deck_card import extract_deck_names

                first = dict(templates[0])
                names = extract_deck_names(first)
                if len(names) == 8:
                    sanity = validate_deck_sanity(names)
                    first["sanity_report"] = sanity.to_dict()
                    if not sanity.passed:
                        first["balanced"] = False
                    templates[0] = first
                deck_card = deck_card_from_entry(templates[0], arena=arena_label)
                data = {
                    "core": core,
                    "decks": templates[:3],
                    "mode": "meta_templates",
                    "sanity_report": templates[0].get("sanity_report"),
                }
                if deck_card:
                    data["deck_card"] = deck_card
                    ctx.deck_card = deck_card
                return ToolResult(
                    tool=self.name,
                    ok=True,
                    data=data,
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
