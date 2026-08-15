"""Tool: Deck Builder — всегда возвращает готовую колоду (staged fallback)."""

from __future__ import annotations

from bot.services.card_names_ru import card_name_ru
from bot.services.deck_builder.staged_build import (
    STAGE_ARCHETYPE,
    STAGE_FREEFORM,
    STAGE_META,
    build_decks_staged,
)
from bot.services.deck_constructor import build_constructor_decks
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.deck_card import deck_card_from_entry, format_arena_label
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.tools.base import BaseTool
from bot.services.ghosteek_ai.tools.schema import COMMON_INPUT_PROPERTIES, object_schema


def _entries_from_build_results(
    build_results: list,
    seed: list[str],
    *,
    arena_id: int | None,
    trophies: int | None,
    mode: str,
) -> list[dict]:
    from bot.services.card_icons import deck_card_info_from_parsed
    from bot.services.card_registry import get_card_info
    from bot.services.counter_engine import _get_arena_pool
    from bot.services.deck_constructor import _entries_from_results

    core_parsed = []
    for i, name in enumerate(seed[:4]):
        info = get_card_info(name) or {}
        core_parsed.append({
            "name": name,
            "icon": info.get("icon") or "",
            "evolution_level": 0,
            "is_hero": False,
            "cost": int(info.get("elixir") or 4),
            "slot": i,
        })
    pool = set(_get_arena_pool(arena_id, trophies))
    pool.update(seed)
    entries = _entries_from_results(
        build_results,
        core_parsed,
        pool,
        limit=max(1, len(build_results)),
        id_start=7100,
        is_alternative=False,
    )
    for entry in entries:
        entry["type"] = "constructor"
        entry["build_stage"] = mode
        # Ensure cards present even if enrich skipped
        if not entry.get("cards") and build_results:
            names = build_results[0].deck
            entry["cards"] = [
                deck_card_info_from_parsed(
                    {
                        "name": n,
                        "icon": (get_card_info(n) or {}).get("icon") or "",
                        "evolution_level": 0,
                        "is_hero": False,
                        "cost": int((get_card_info(n) or {}).get("elixir") or 4),
                        "slot": i,
                    },
                    slot=i,
                )
                for i, n in enumerate(names)
            ]
    return entries


def _attach_sanity(decks: list[dict]) -> list[dict]:
    if not decks:
        return decks
    from bot.services.deck_sanity_validator import validate_deck_sanity
    from bot.services.ghosteek_ai.deck_card import extract_deck_names

    first = dict(decks[0])
    names = extract_deck_names(first)
    if len(names) == 8:
        sanity = validate_deck_sanity(names)
        first["sanity_report"] = sanity.to_dict()
        if not sanity.passed:
            first["balanced"] = False
        decks = [first, *decks[1:]]
    return decks


class DeckBuilderTool(BaseTool):
    name = "deck_builder"
    description = (
        "Build a complete 8-card deck from a win-condition / key card "
        "or a 4-card core. Always returns a playable deck when cards exist. "
        "Returns structured deck_card for UI — do not list cards in text."
    )
    input_schema = object_schema({"cards": COMMON_INPUT_PROPERTIES["cards"]})

    async def execute(self, ctx: AIContext) -> ToolResult:
        user = ctx.require_user()
        core = ctx.cards_arg()
        arena_label = format_arena_label(ctx.arena.arena_id, ctx.arena.trophies)
        del user

        # ---- 4-card constructor path (UI core) ----
        if len(core) >= 4:
            slots = [{"name": n, "slot": i} for i, n in enumerate(core[:4])]
            result = build_constructor_decks(
                slots,
                arena_id=ctx.arena.arena_id,
                trophies=ctx.arena.trophies,
                limit=3,
            )
            decks = list(result.get("decks") or [])
            # Promote Stage-2 alternative so Ghosteek never sees an empty list.
            alt = result.get("alternative_deck")
            if not decks and isinstance(alt, dict):
                decks = [alt]
            if not decks:
                # Last resort: staged freeform around the 4 cards
                staged = build_decks_staged(
                    core[:4],
                    arena_id=ctx.arena.arena_id,
                    trophies=ctx.arena.trophies,
                    limit=3,
                )
                if staged.get("ok") and staged.get("build_results"):
                    decks = _entries_from_build_results(
                        staged["build_results"],
                        core[:4],
                        arena_id=ctx.arena.arena_id,
                        trophies=ctx.arena.trophies,
                        mode=str(staged.get("mode") or STAGE_FREEFORM),
                    )
            if not decks:
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    error_code="NO_VALID_BUILD",
                    error_params={
                        "card_ru": card_name_ru(core[0]),
                        "reason": "Не удалось собрать стабильную колоду из выбранного ядра.",
                        "suggestion": "Добавьте спелл или поддержку в ядро и попробуйте снова.",
                    },
                    data={"core": core[:4]},
                    actions=[{"type": "navigate", "path": "/decks"}],
                )
            decks = _attach_sanity(decks)
            deck_card = deck_card_from_entry(decks[0], arena=arena_label)
            data: dict = {
                "core": core[:4],
                "decks": decks[:3],
                "mode": "constructor",
                "stage": STAGE_FREEFORM if result.get("alternative_deck") and not result.get("decks") else STAGE_META,
            }
            if deck_card:
                data["deck_card"] = deck_card
                ctx.deck_card = deck_card
            if decks[0].get("sanity_report"):
                data["sanity_report"] = decks[0]["sanity_report"]
            return ToolResult(
                tool=self.name,
                ok=True,
                data=data,
                actions=[{"type": "navigate", "path": "/decks"}],
            )

        # ---- 1–3 cards: staged pipeline (meta → freeform → archetype) ----
        if len(core) >= 1:
            staged = build_decks_staged(
                core,
                arena_id=ctx.arena.arena_id,
                trophies=ctx.arena.trophies,
                limit=3,
            )
            if not staged.get("ok"):
                code = staged.get("error_code") or staged.get("status") or "BUILD_UNKNOWN_CARD"
                params = dict(staged.get("error_params") or {})
                if staged.get("reason"):
                    params.setdefault("reason", staged["reason"])
                if staged.get("suggestion"):
                    params.setdefault("suggestion", staged["suggestion"])
                if "card_ru" not in params:
                    params["card_ru"] = card_name_ru(core[0])
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    error_code=code,
                    error_params=params,
                    data={"core": core, "status": staged.get("status") or code},
                    actions=[{"type": "navigate", "path": "/decks"}],
                )

            mode = str(staged.get("mode") or STAGE_FREEFORM)
            decks: list[dict]
            if mode == STAGE_META:
                decks = list(staged.get("decks") or [])
            else:
                decks = _entries_from_build_results(
                    staged.get("build_results") or [],
                    list(staged.get("core") or core),
                    arena_id=ctx.arena.arena_id,
                    trophies=ctx.arena.trophies,
                    mode=mode,
                )

            if not decks:
                return ToolResult(
                    tool=self.name,
                    ok=False,
                    error_code="NO_VALID_BUILD",
                    error_params={
                        "card_ru": card_name_ru(core[0]),
                        "reason": staged.get("reason")
                        or "Не удалось собрать стабильную колоду.",
                        "suggestion": staged.get("suggestion")
                        or "Добавьте ещё карты в ядро или смените главную угрозу.",
                    },
                    data={"core": core, "status": "NO_VALID_BUILD"},
                    actions=[{"type": "navigate", "path": "/decks"}],
                )

            decks = _attach_sanity(decks)
            deck_card = deck_card_from_entry(decks[0], arena=arena_label)
            data = {
                "core": core,
                "decks": decks[:3],
                "mode": mode,
                "stage": staged.get("stage") or mode,
                "sanity_report": decks[0].get("sanity_report"),
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

        # Нет карт вообще — единственный «человеческий» clarify (не внутренний отказ).
        return ToolResult(
            tool=self.name,
            ok=False,
            error_code="BUILD_NEED_CARD",
            actions=[{"type": "navigate", "path": "/decks"}],
        )
