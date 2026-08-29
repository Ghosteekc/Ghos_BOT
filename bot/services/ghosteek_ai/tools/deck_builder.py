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

    out: list[dict] = []
    for raw in decks:
        entry = dict(raw)
        names = extract_deck_names(entry)
        if len(names) == 8:
            sanity = validate_deck_sanity(names)
            entry["sanity_report"] = sanity.to_dict()
            if not sanity.passed:
                entry["balanced"] = False
        out.append(entry)
    return out


def _entry_names(entry: dict) -> list[str]:
    from bot.services.ghosteek_ai.deck_card import extract_deck_names

    return extract_deck_names(entry)[:8]


def _deck_key(names: list[str]) -> str:
    return "|".join(sorted(n for n in names if n))


def _filter_excluded_decks(
    decks: list[dict],
    exclude_decks: list[list[str]] | None,
    *,
    limit: int,
) -> list[dict]:
    excluded = {
        _deck_key(list(d)[:8])
        for d in (exclude_decks or [])
        if isinstance(d, list) and len(d) >= 8
    }
    if not excluded:
        return decks[:limit]
    filtered: list[dict] = []
    for entry in decks:
        names = _entry_names(entry)
        if len(names) >= 8 and _deck_key(names) in excluded:
            continue
        filtered.append(entry)
        if len(filtered) >= limit:
            break
    return filtered if filtered else decks[:limit]


def _resolve_build_limit(ctx: AIContext) -> int:
    raw = ctx.arg("build_limit")
    if raw is None and isinstance(ctx.request_context, dict):
        raw = ctx.request_context.get("build_limit")
    try:
        n = int(raw) if raw is not None else 1
    except (TypeError, ValueError):
        n = 1
    return max(1, min(3, n))


def _resolve_exclude_decks(ctx: AIContext) -> list[list[str]]:
    raw = ctx.arg("exclude_decks")
    if raw is None and isinstance(ctx.request_context, dict):
        raw = ctx.request_context.get("exclude_decks")
    out: list[list[str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, list):
                names = [c for c in item if isinstance(c, str)][:8]
                if len(names) >= 8:
                    out.append(names)
    prefer = ctx.arg("prefer_alternative")
    if prefer is None and isinstance(ctx.request_context, dict):
        prefer = ctx.request_context.get("prefer_alternative")
    if prefer and ctx.session.last_deck and len(ctx.session.last_deck) >= 8:
        out.append(list(ctx.session.last_deck)[:8])
    shown = getattr(ctx.session, "last_build_shown", None) or []
    for d in shown:
        if isinstance(d, list) and len(d) >= 8:
            out.append([c for c in d if isinstance(c, str)][:8])
    return out


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
        # Не подставлять прошлую 8-карточную колоду как «ядро» для builder.
        if len(core) >= 8 and getattr(ctx.session, "last_build_core", None):
            build_core = [c for c in ctx.session.last_build_core if isinstance(c, str)][:4]
            if build_core and set(build_core).issubset(set(core)):
                core = build_core
        arena_label = format_arena_label(ctx.arena.arena_id, ctx.arena.trophies)
        del user
        build_limit = _resolve_build_limit(ctx)
        exclude_decks = _resolve_exclude_decks(ctx)
        # Генерируем с запасом, чтобы отфильтровать уже показанные.
        gen_limit = min(3, build_limit + (1 if exclude_decks else 0))

        # ---- 4-card constructor path (UI core) ----
        if len(core) >= 4:
            slots = [{"name": n, "slot": i} for i, n in enumerate(core[:4])]
            result = build_constructor_decks(
                slots,
                arena_id=ctx.arena.arena_id,
                trophies=ctx.arena.trophies,
                limit=gen_limit,
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
                    limit=gen_limit,
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
            decks = _filter_excluded_decks(decks, exclude_decks, limit=build_limit)
            decks = _attach_sanity(decks)
            deck_card = deck_card_from_entry(decks[0], arena=arena_label)
            deck_cards = [
                c
                for c in (deck_card_from_entry(d, arena=arena_label) for d in decks[:build_limit])
                if c
            ]
            data: dict = {
                "core": core[:4],
                "decks": decks[:build_limit],
                "mode": "constructor",
                "stage": STAGE_FREEFORM if result.get("alternative_deck") and not result.get("decks") else STAGE_META,
                "deck_cards": deck_cards,
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
                limit=gen_limit,
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

            decks = _filter_excluded_decks(decks, exclude_decks, limit=build_limit)
            decks = _attach_sanity(decks)
            deck_card = deck_card_from_entry(decks[0], arena=arena_label)
            deck_cards = [
                c
                for c in (deck_card_from_entry(d, arena=arena_label) for d in decks[:build_limit])
                if c
            ]
            data = {
                "core": core,
                "decks": decks[:build_limit],
                "mode": mode,
                "stage": staged.get("stage") or mode,
                "sanity_report": decks[0].get("sanity_report"),
                "deck_cards": deck_cards,
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
