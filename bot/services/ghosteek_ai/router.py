"""Роутер: intent → существующие сервисы / Knowledge Base / Game Coach."""

from __future__ import annotations

from typing import Any

from bot.models.database import User
from bot.services.battle_report import analyze_battle_enhanced
from bot.services.battle_service import load_and_persist
from bot.services.card_matchups import calculate_deck_synergy
from bot.services.card_names_ru import card_name_ru
from bot.services.card_profile import get_card_profile
from bot.services.deck_constructor import build_constructor_decks
from bot.services.ghosteek_ai.game_coach import (
    CLIMB_TIPS,
    decks_for_win_condition,
    resolve_archetype_deck,
)
from bot.services.ghosteek_ai.intents import (
    CLARIFY_PROMPT,
    INTENT_ANALYZE_DECK,
    INTENT_BUILD_DECK,
    INTENT_CARD_INFO,
    INTENT_CLARIFY,
    INTENT_EXPLAIN_MECHANIC,
    INTENT_GAME_COACH,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    INTENT_MATCHUP,
    INTENT_UNSUPPORTED,
    SERVICE_BY_INTENT,
    DetectedIntent,
)
from bot.services.ghosteek_ai.knowledge_base import list_mechanic_titles, lookup_mechanic
from bot.services.ghosteek_ai.voice import coach_reply
from bot.services.matchup_evaluation import evaluate_matchup
from bot.services.recommendation_engine import RecommendationEngine


def _payload(
    intent: str,
    *,
    ok: bool,
    data: dict[str, Any] | None = None,
    error: str | None = None,
    actions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "service": SERVICE_BY_INTENT.get(intent, "Clarify"),
        "ok": ok,
        "error": error,
        "data": data or {},
        "actions": actions or [],
    }


async def _resolve_player_deck(user: User, fallback: list[str]) -> list[str]:
    if len(fallback) >= 8:
        return fallback[:8]
    tag = user.player_tag or ""
    if not tag:
        return fallback
    try:
        from bot.services.clash_api import ClashRoyaleClient
        from bot.services.top_players import _cards_from_current_deck

        client = ClashRoyaleClient()
        try:
            player = await client.get_player(tag)
            parsed = _cards_from_current_deck(player)
            names = [c["name"] for c in parsed if c.get("name")]
            if len(names) >= 8:
                return names[:8]
        finally:
            await client.close()
    except Exception:
        pass
    battles = await load_and_persist(user)
    if battles:
        team = battles[0].get("team", [{}])[0]
        names = [c.get("name") for c in team.get("cards", []) if c.get("name")]
        if len(names) >= 8:
            return names[:8]
    return fallback


async def route_intent(
    detected: DetectedIntent,
    user: User,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Возвращает payload: intent / service / ok / data / error / actions."""
    ctx = context or {}
    intent = detected.intent

    if intent == INTENT_UNSUPPORTED:
        return _payload(
            intent,
            ok=False,
            error=coach_reply(
                "Этих данных у Clash Royale просто нет.",
                why="Точный урон по картам в бою, эликсир в руке и кадры реплея API не отдаёт.",
                action="Могу разобрать колоду, матчап, бой или объяснить механику.",
                tip="Скажи, что именно нужно — подскажу по делу.",
            ),
        )

    if intent == INTENT_CLARIFY:
        return _payload(intent, ok=False, error=CLARIFY_PROMPT)

    if intent == INTENT_LAST_BATTLE:
        return await _route_last_battle(user, ctx)

    if intent == INTENT_EXPLAIN_MECHANIC:
        return _route_mechanic(detected.mechanic_query)

    if intent == INTENT_GAME_COACH:
        return await _route_game_coach(user, detected, ctx)

    if intent == INTENT_CARD_INFO:
        return _route_card_info(detected.card_query or (detected.cards[0] if detected.cards else None))

    if intent == INTENT_BUILD_DECK:
        return _route_build(detected.cards, user)

    if intent in {INTENT_ANALYZE_DECK, INTENT_IMPROVE_DECK}:
        deck = await _resolve_player_deck(user, detected.cards)
        if len(deck) < 8:
            return _payload(
                intent,
                ok=False,
                error=coach_reply(
                    "Нужна колода из 8 карт.",
                    why="Без состава совет будет пустым.",
                    action="Пришли названия карт или привяжи тег — возьму текущую колоду из профиля.",
                    tip="Потом разберём или улучшим уже по факту.",
                ),
                actions=[{"type": "navigate", "path": "/decks"}],
            )
        return _route_deck_recommendation(intent, deck)

    if intent == INTENT_MATCHUP:
        return await _route_matchup(user, detected, ctx)

    return _payload(INTENT_CLARIFY, ok=False, error=CLARIFY_PROMPT)


def _route_card_info(name: str | None) -> dict[str, Any]:
    if not name:
        return _payload(
            INTENT_CARD_INFO,
            ok=False,
            error=coach_reply(
                "Какую карту разбираем?",
                action="Напиши, например: «что делает Палач».",
                tip="Тогда дам роль и как её обычно ставят в колоду.",
            ),
        )
    profile = get_card_profile(name)
    return _payload(
        INTENT_CARD_INFO,
        ok=True,
        data={
            "name": name,
            "name_ru": card_name_ru(name),
            "elixir": profile.elixir,
            "card_type": profile.card_type,
            "roles": sorted(profile.roles),
        },
    )


def _route_mechanic(key: str | None) -> dict[str, Any]:
    entry = lookup_mechanic(key)
    if entry is None:
        titles = ", ".join(list_mechanic_titles()[:6])
        return _payload(
            INTENT_EXPLAIN_MECHANIC,
            ok=False,
            error=coach_reply(
                "Этой механики в базе пока нет.",
                why=f"Могу объяснить, например: {titles}.",
                action="Напиши термин точнее — разберём.",
                tip="Формулировка «что такое cycle» работает лучше всего.",
            ),
        )
    return _payload(
        INTENT_EXPLAIN_MECHANIC,
        ok=True,
        data={
            "key": entry.key,
            "title": entry.title,
            "summary": entry.summary,
            "tips": list(entry.tips),
        },
    )


def _route_deck_recommendation(intent: str, deck: list[str]) -> dict[str, Any]:
    rec = RecommendationEngine.analyze(deck, apply_swaps=intent == INTENT_IMPROVE_DECK)
    synergy_score, synergy_notes = calculate_deck_synergy(deck)
    public = rec.to_public_dict()
    return _payload(
        intent,
        ok=True,
        data={
            "deck": deck,
            "recommendation": public,
            "synergy_score": synergy_score,
            "synergy_notes": synergy_notes,
        },
        actions=[{"type": "navigate", "path": "/decks"}],
    )


def _route_build(core: list[str], user: User) -> dict[str, Any]:
    # 4 карты → конструктор
    if len(core) >= 4:
        slots = [{"name": n, "slot": i} for i, n in enumerate(core[:4])]
        result = build_constructor_decks(
            slots,
            arena_id=user.arena_id,
            trophies=user.trophies,
            limit=3,
        )
        decks = result.get("decks") or []
        if not decks:
            return _payload(
                INTENT_BUILD_DECK,
                ok=False,
                error=coach_reply(
                    "Вокруг этого ядра пока не собрал стабильный вариант.",
                    why="Конструктор не нашёл подходящую сборку.",
                    action="Попробуй другое ядро из 4 карт или другой win condition.",
                    tip="Пример: Хог, Терпила, Мушкетёр, Пушка.",
                ),
                data={"core": core[:4]},
                actions=[{"type": "navigate", "path": "/decks"}],
            )
        return _payload(
            INTENT_BUILD_DECK,
            ok=True,
            data={"core": core[:4], "decks": decks[:3], "mode": "constructor"},
            actions=[{"type": "navigate", "path": "/decks"}],
        )

    # 1–3 карты: шаблоны META_DECKS по win condition (без новой эвристики сборки)
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
            return _payload(
                INTENT_BUILD_DECK,
                ok=True,
                data={
                    "core": core,
                    "decks": templates[:3],
                    "mode": "meta_templates",
                },
                actions=[{"type": "navigate", "path": "/decks"}],
            )
        return _payload(
            INTENT_BUILD_DECK,
            ok=False,
            error=coach_reply(
                f"Готовых шаблонов вокруг «{card_name_ru(core[0])}» нет.",
                why="В базе нет подходящей колоды под эту опору.",
                action="Дай ядро из 4 карт — соберём точнее.",
                tip="Пример: «собери колоду вокруг Хог Терпила Мушкетёр Пушка».",
            ),
            data={"core": core},
            actions=[{"type": "navigate", "path": "/decks"}],
        )

    return _payload(
        INTENT_BUILD_DECK,
        ok=False,
        error=coach_reply(
            "Чтобы собрать колоду, нужен ориентир.",
            why="Без win condition или ядра сборка будет гаданием.",
            action="Напиши «хочу играть через Хога» или 4 карты ядра.",
            tip="После этого дам готовый вариант под твой стиль.",
        ),
        actions=[{"type": "navigate", "path": "/decks"}],
    )


async def _route_game_coach(
    user: User,
    detected: DetectedIntent,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    topic = detected.coach_topic or "general"

    if topic == "climb":
        return _payload(
            INTENT_GAME_COACH,
            ok=True,
            data={"topic": "climb", "tips": list(CLIMB_TIPS)},
            actions=[
                {"type": "navigate", "path": "/battles"},
                {"type": "navigate", "path": "/analytics"},
            ],
        )

    # vs_advice — эталон из META_DECKS + MatchupEvaluation по колоде игрока
    arch = resolve_archetype_deck(detected.raw)
    if arch is None and topic == "vs_advice":
        return _payload(
            INTENT_GAME_COACH,
            ok=False,
            error=coach_reply(
                "Против кого готовимся?",
                why="Нужен конкретный архетип.",
                action="Напиши, например: «как играть против Lavaloon» или «против Хог 2.6».",
                tip="Тогда разберём план под твою колоду.",
            ),
        )

    if arch is not None:
        arch_name, opp_deck = arch
        user_deck = await _resolve_player_deck(user, detected.cards)
        if len(user_deck) < 8 and isinstance(ctx.get("cards"), list):
            user_deck = [c for c in ctx["cards"] if isinstance(c, str)][:8]
        if len(user_deck) < 8:
            return _payload(
                INTENT_GAME_COACH,
                ok=False,
                error=coach_reply(
                    f"Против «{arch_name}» нужен твой состав.",
                    why="Без твоей колоды из 8 карт совет будет общим и пустым.",
                    action="Пришли колоду или привяжи тег.",
                    tip="Можно также разобрать матчап, если дашь обе колоды.",
                ),
                data={"archetype": arch_name, "opponent_deck": opp_deck},
                actions=[{"type": "navigate", "path": "/decks/compare"}],
            )
        evaluation = evaluate_matchup(user_deck[:8], opp_deck)
        return _payload(
            INTENT_GAME_COACH,
            ok=True,
            data={
                "topic": "vs_advice",
                "archetype": arch_name,
                "user_deck": user_deck[:8],
                "opponent_deck": opp_deck,
                "score": evaluation.score,
                "rating": evaluation.rating,
                "reasons": evaluation.reasons,
                "advantages": evaluation.advantages,
                "disadvantages": evaluation.disadvantages,
                "tips": [
                    "Оценка — по эталонной колоде архетипа из базы Ghosteek.",
                    "Свой последний бой с таким соперником разберём отдельно.",
                ],
            },
            actions=[{"type": "navigate", "path": "/decks/compare"}],
        )

    return _payload(
        INTENT_GAME_COACH,
        ok=False,
        error=coach_reply(
            "Уточни совет.",
            action="«Как апнуть кубки?» или «как играть против Lavaloon?»",
            tip="Чем конкретнее вопрос — тем точнее план.",
        ),
    )


async def _route_last_battle(user: User, ctx: dict[str, Any]) -> dict[str, Any]:
    battles = await load_and_persist(user)
    if not battles:
        return _payload(
            INTENT_LAST_BATTLE,
            ok=False,
            error=coach_reply(
                "Истории боёв пока нет.",
                why="Без боя разбирать нечего.",
                action="Синхронизируй бои или сыграй ladder/PvP.",
                tip="После этого разберём последний матч по шагам.",
            ),
            actions=[{"type": "navigate", "path": "/battles"}],
        )

    index = ctx.get("battle_index")
    if isinstance(index, int) and 0 <= index < len(battles):
        battle = battles[index]
        battle_index = index
    else:
        battle = battles[0]
        battle_index = 0

    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]
    duration = int(battle.get("gameDuration") or 0)
    analysis = analyze_battle_enhanced(team, opponent, duration=duration)

    return _payload(
        INTENT_LAST_BATTLE,
        ok=True,
        data={
            "battle_index": battle_index,
            "won": analysis.won,
            "opponent_name": analysis.opponent_name,
            "matchup_score": analysis.matchup_score,
            "outcome_summary": analysis.outcome_summary,
            "reasons": analysis.reasons[:6],
            "match_difficulty": (
                {
                    "difficulty": analysis.match_difficulty.difficulty,
                    "rating": analysis.match_difficulty.rating,
                    "reasons": analysis.match_difficulty.reasons[:4],
                }
                if analysis.match_difficulty
                else None
            ),
            "match_plan": (
                {
                    "win_condition_window": analysis.match_plan.win_condition_window,
                    "avoid": analysis.match_plan.avoid[:3],
                    "phase_1": analysis.match_plan.game_plan.phase_1[:2],
                }
                if analysis.match_plan
                else None
            ),
        },
        actions=[{"type": "navigate", "path": f"/battles/{battle_index}"}],
    )


async def _route_matchup(
    user: User,
    detected: DetectedIntent,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    user_deck = await _resolve_player_deck(user, detected.cards)
    opp = detected.opponent_cards
    if len(opp) < 8 and isinstance(ctx.get("opponent_cards"), list):
        opp = [c for c in ctx["opponent_cards"] if isinstance(c, str)]

    if len(opp) < 8:
        battles = await load_and_persist(user)
        if battles:
            opponent = battles[0].get("opponent", [{}])[0]
            opp = [c.get("name") for c in opponent.get("cards", []) if c.get("name")]
            if len(user_deck) < 8:
                team = battles[0].get("team", [{}])[0]
                user_deck = [c.get("name") for c in team.get("cards", []) if c.get("name")]

    if len(user_deck) < 8 or len(opp) < 8:
        return _payload(
            INTENT_MATCHUP,
            ok=False,
            error=coach_reply(
                "Для матчапа мало данных.",
                why="Нужны две колоды по 8 карт или хотя бы один бой в истории.",
                action="Пришли обе колоды или сыграй бой и синхронизируй историю.",
                tip="Тогда скажу, где давить и где лучше подождать.",
            ),
            actions=[{"type": "navigate", "path": "/battles"}],
        )

    evaluation = evaluate_matchup(user_deck[:8], opp[:8])
    return _payload(
        INTENT_MATCHUP,
        ok=True,
        data={
            "user_deck": user_deck[:8],
            "opponent_deck": opp[:8],
            "score": evaluation.score,
            "rating": evaluation.rating,
            "reasons": evaluation.reasons,
            "advantages": evaluation.advantages,
            "disadvantages": evaluation.disadvantages,
        },
        actions=[{"type": "navigate", "path": "/decks/compare"}],
    )
