"""Роутер: intent → существующие сервисы (без новой аналитики)."""

from __future__ import annotations

from typing import Any

from bot.models.database import User
from bot.services.battle_report import analyze_battle_enhanced
from bot.services.battle_service import get_cached_stats, load_and_persist
from bot.services.card_matchups import calculate_deck_synergy
from bot.services.card_names_ru import card_name_ru
from bot.services.card_profile import get_card_profile
from bot.services.deck_constructor import build_constructor_decks
from bot.services.ghosteek_ai.intents import (
    INTENT_ANALYZE_DECK,
    INTENT_BUILD_DECK,
    INTENT_CARD_INFO,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    INTENT_MATCHUP,
    INTENT_META,
    INTENT_STATS,
    INTENT_UNSUPPORTED,
    INTENT_UNKNOWN,
    DetectedIntent,
)
from bot.services.matchup_evaluation import evaluate_matchup
from bot.services.meta_analyzer import get_live_meta_decks
from bot.services.recommendation_engine import RecommendationEngine


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
    """Возвращает payload с ключами intent / ok / data / error / actions."""
    ctx = context or {}
    intent = detected.intent

    if intent == INTENT_UNSUPPORTED:
        return {
            "intent": intent,
            "ok": False,
            "error": (
                "Clash Royale не предоставляет эти данные "
                "(точный урон по картам в бою, эликсир в руке и т.п.). "
                "Могу разобрать колоду, матчап, последний бой, мету или статистику."
            ),
            "data": {},
            "actions": [],
        }

    if intent == INTENT_UNKNOWN:
        return {
            "intent": intent,
            "ok": False,
            "error": (
                "Не понял запрос. Попробуйте: «разбери мою колоду», «последний бой», "
                "«что в мете», «мой винрейт», «собери колоду вокруг Хог»."
            ),
            "data": {},
            "actions": [],
        }

    if intent == INTENT_LAST_BATTLE:
        return await _route_last_battle(user, ctx)

    if intent == INTENT_STATS:
        return await _route_stats(user)

    if intent == INTENT_META:
        return await _route_meta()

    if intent == INTENT_CARD_INFO:
        return _route_card_info(detected.card_query or (detected.cards[0] if detected.cards else None))

    if intent == INTENT_BUILD_DECK:
        return _route_build(detected.cards, user)

    if intent in {INTENT_ANALYZE_DECK, INTENT_IMPROVE_DECK}:
        deck = await _resolve_player_deck(user, detected.cards)
        if len(deck) < 8:
            return {
                "intent": intent,
                "ok": False,
                "error": (
                    "Нужна колода из 8 карт. Пришлите названия карт или привяжите тег, "
                    "чтобы взять текущую колоду из профиля."
                ),
                "data": {},
                "actions": [{"type": "navigate", "path": "/decks"}],
            }
        return _route_deck_recommendation(intent, deck)

    if intent == INTENT_MATCHUP:
        return await _route_matchup(user, detected, ctx)

    return {
        "intent": INTENT_UNKNOWN,
        "ok": False,
        "error": "Неизвестный сценарий.",
        "data": {},
        "actions": [],
    }


def _route_card_info(name: str | None) -> dict[str, Any]:
    if not name:
        return {
            "intent": INTENT_CARD_INFO,
            "ok": False,
            "error": "Укажите карту, например: «что делает Палач».",
            "data": {},
            "actions": [],
        }
    profile = get_card_profile(name)
    return {
        "intent": INTENT_CARD_INFO,
        "ok": True,
        "error": None,
        "data": {
            "name": name,
            "name_ru": card_name_ru(name),
            "elixir": profile.elixir,
            "card_type": profile.card_type,
            "roles": sorted(profile.roles),
        },
        "actions": [],
    }


def _route_deck_recommendation(intent: str, deck: list[str]) -> dict[str, Any]:
    rec = RecommendationEngine.analyze(deck, apply_swaps=intent == INTENT_IMPROVE_DECK)
    synergy_score, synergy_notes = calculate_deck_synergy(deck)
    public = rec.to_public_dict()
    return {
        "intent": intent,
        "ok": True,
        "error": None,
        "data": {
            "deck": deck,
            "recommendation": public,
            "synergy_score": synergy_score,
            "synergy_notes": synergy_notes,
        },
        "actions": [{"type": "navigate", "path": "/decks"}],
    }


def _route_build(core: list[str], user: User) -> dict[str, Any]:
    if len(core) < 4:
        return {
            "intent": INTENT_BUILD_DECK,
            "ok": False,
            "error": "Для сборки нужно ядро из 4 карт. Пример: «собери колоду вокруг Хог Терпила Мушкетёр Пушка».",
            "data": {},
            "actions": [{"type": "navigate", "path": "/decks"}],
        }
    slots = [{"name": n, "slot": i} for i, n in enumerate(core[:4])]
    result = build_constructor_decks(
        slots,
        arena_id=user.arena_id,
        trophies=user.trophies,
        limit=3,
    )
    decks = result.get("decks") or []
    if not decks:
        return {
            "intent": INTENT_BUILD_DECK,
            "ok": False,
            "error": "Конструктор не смог собрать колоду вокруг этого ядра.",
            "data": {"core": core[:4]},
            "actions": [{"type": "navigate", "path": "/decks"}],
        }
    return {
        "intent": INTENT_BUILD_DECK,
        "ok": True,
        "error": None,
        "data": {
            "core": core[:4],
            "decks": decks[:3],
        },
        "actions": [{"type": "navigate", "path": "/decks"}],
    }


async def _route_stats(user: User) -> dict[str, Any]:
    stats = await get_cached_stats(user.player_tag or "")
    if not stats:
        return {
            "intent": INTENT_STATS,
            "ok": False,
            "error": "Нет сохранённой статистики боёв. Синхронизируйте историю боёв.",
            "data": {},
            "actions": [{"type": "navigate", "path": "/battles"}],
        }
    return {
        "intent": INTENT_STATS,
        "ok": True,
        "error": None,
        "data": {
            "total": stats.total,
            "wins": stats.wins,
            "losses": stats.losses,
            "winrate": stats.winrate,
            "win_streak": stats.win_streak,
            "loss_streak": stats.loss_streak,
            "top_decks": stats.top_decks[:3],
        },
        "actions": [{"type": "navigate", "path": "/analytics"}],
    }


async def _route_meta() -> dict[str, Any]:
    try:
        meta = await get_live_meta_decks()
        decks = list(meta.decks or [])[:5]
    except Exception:
        decks = []
    if not decks:
        return {
            "intent": INTENT_META,
            "ok": False,
            "error": "Мета сейчас недоступна. Откройте раздел колод или повторите позже.",
            "data": {},
            "actions": [{"type": "navigate", "path": "/decks"}],
        }
    compact = []
    for d in decks:
        if not isinstance(d, dict):
            continue
        cards = d.get("cards") or []
        names: list[str] = []
        if isinstance(cards, list):
            for c in cards:
                if isinstance(c, str):
                    names.append(c)
                elif isinstance(c, dict) and c.get("name"):
                    names.append(c["name"])
        compact.append({
            "cards": names[:8],
            "name": d.get("name") or d.get("title"),
            "winrate": d.get("winrate"),
            "usage": d.get("usage") or d.get("usage_rate"),
        })
    return {
        "intent": INTENT_META,
        "ok": True,
        "error": None,
        "data": {"decks": compact},
        "actions": [{"type": "navigate", "path": "/decks"}],
    }


async def _route_last_battle(user: User, ctx: dict[str, Any]) -> dict[str, Any]:
    battles = await load_and_persist(user)
    if not battles:
        return {
            "intent": INTENT_LAST_BATTLE,
            "ok": False,
            "error": "Нет истории боёв. Синхронизируйте бои или сыграйте ladder/PvP.",
            "data": {},
            "actions": [{"type": "navigate", "path": "/battles"}],
        }

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

    path = f"/battles/{battle_index}"
    return {
        "intent": INTENT_LAST_BATTLE,
        "ok": True,
        "error": None,
        "data": {
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
        "actions": [{"type": "navigate", "path": path}],
    }


async def _route_matchup(
    user: User,
    detected: DetectedIntent,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    user_deck = await _resolve_player_deck(user, detected.cards)
    opp = detected.opponent_cards
    if len(opp) < 8 and isinstance(ctx.get("opponent_cards"), list):
        opp = [c for c in ctx["opponent_cards"] if isinstance(c, str)]

    # Если нет второй колоды — берём последнего соперника из истории
    if len(opp) < 8:
        battles = await load_and_persist(user)
        if battles:
            opponent = battles[0].get("opponent", [{}])[0]
            opp = [c.get("name") for c in opponent.get("cards", []) if c.get("name")]
            if len(user_deck) < 8:
                team = battles[0].get("team", [{}])[0]
                user_deck = [c.get("name") for c in team.get("cards", []) if c.get("name")]

    if len(user_deck) < 8 or len(opp) < 8:
        return {
            "intent": INTENT_MATCHUP,
            "ok": False,
            "error": (
                "Для матчапа нужны две колоды по 8 карт или хотя бы один бой в истории."
            ),
            "data": {},
            "actions": [{"type": "navigate", "path": "/battles"}],
        }

    evaluation = evaluate_matchup(user_deck[:8], opp[:8])
    return {
        "intent": INTENT_MATCHUP,
        "ok": True,
        "error": None,
        "data": {
            "user_deck": user_deck[:8],
            "opponent_deck": opp[:8],
            "score": evaluation.score,
            "rating": evaluation.rating,
            "reasons": evaluation.reasons,
            "advantages": evaluation.advantages,
            "disadvantages": evaluation.disadvantages,
        },
        "actions": [{"type": "navigate", "path": "/decks/compare"}],
    }
