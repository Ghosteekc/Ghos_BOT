"""Сборка ответа игроку только из payload сервисов."""

from __future__ import annotations

from typing import Any

from bot.services.card_names_ru import card_name_ru
from bot.services.ghosteek_ai.intents import (
    INTENT_ANALYZE_DECK,
    INTENT_BUILD_DECK,
    INTENT_CARD_INFO,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    INTENT_MATCHUP,
    INTENT_META,
    INTENT_STATS,
)


def _ru_list(cards: list[str], *, limit: int = 8) -> str:
    return ", ".join(card_name_ru(c, short=True) for c in cards[:limit])


def compose_answer(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return str(payload.get("error") or "Нет данных для ответа.")

    intent = payload.get("intent")
    data = payload.get("data") or {}

    if intent == INTENT_CARD_INFO:
        roles = ", ".join(data.get("roles") or []) or "—"
        return (
            f"{data.get('name_ru') or data.get('name')} — "
            f"{data.get('elixir')} эл., тип: {data.get('card_type')}, роли: {roles}. "
            f"Это данные из базы карт Ghosteek; боевые статы CR API не отдаёт."
        )

    if intent in {INTENT_ANALYZE_DECK, INTENT_IMPROVE_DECK}:
        return _compose_recommendation(intent, data)

    if intent == INTENT_BUILD_DECK:
        return _compose_build(data)

    if intent == INTENT_STATS:
        return (
            f"Статистика по сохранённым боям: {data.get('wins')}W / {data.get('losses')}L, "
            f"винрейт {data.get('winrate')}% из {data.get('total')} боёв. "
            f"Серия побед: {data.get('win_streak')}, серия поражений: {data.get('loss_streak')}."
        )

    if intent == INTENT_META:
        return _compose_meta(data)

    if intent == INTENT_LAST_BATTLE:
        return _compose_last_battle(data)

    if intent == INTENT_MATCHUP:
        return _compose_matchup(data)

    return "Готово."


def _compose_recommendation(intent: str, data: dict[str, Any]) -> str:
    deck = data.get("deck") or []
    rec = data.get("recommendation") or {}
    lines = [
        f"Колода: {_ru_list(deck)}.",
        f"Синергия (сервис): {data.get('synergy_score')}%.",
    ]
    for note in (data.get("synergy_notes") or [])[:3]:
        lines.append(f"• {note}")

    coaching = rec.get("coaching") or {}
    if coaching:
        if coaching.get("play_style"):
            lines.append(f"Стиль: {coaching['play_style']}.")
        for s in (coaching.get("strengths") or [])[:3]:
            lines.append(f"✔ {s}")
        for tip in (coaching.get("usage_tips") or [])[:2]:
            lines.append(f"Совет: {tip}")

    gp = rec.get("game_plan") or {}
    if gp.get("how_to_win"):
        lines.append(f"Как выигрывать: {gp['how_to_win']}")
    for w in (gp.get("critical_weaknesses") or [])[:2]:
        lines.append(f"Слабость: {w}")

    plan = rec.get("improvement_plan") or {}
    if intent == INTENT_IMPROVE_DECK or plan.get("needed"):
        if plan.get("needed"):
            for step in (plan.get("steps") or [])[:3]:
                msg = step.get("message") if isinstance(step, dict) else str(step)
                lines.append(f"Улучшение: {msg}")
        else:
            lines.append("Критичных замен RecommendationEngine не предлагает.")

    balance = rec.get("balance_issues") or {}
    for msg in (balance.get("messages") or [])[:2]:
        lines.append(f"Баланс: {msg}")

    return "\n".join(lines)


def _compose_build(data: dict[str, Any]) -> str:
    core = data.get("core") or []
    decks = data.get("decks") or []
    lines = [f"Ядро: {_ru_list(core, limit=4)}."]
    for i, entry in enumerate(decks[:3], start=1):
        cards = entry.get("cards") or entry.get("card_names") or []
        if isinstance(cards, list) and cards and isinstance(cards[0], dict):
            names = [c.get("name") for c in cards if c.get("name")]
        else:
            names = [c for c in cards if isinstance(c, str)]
        score = entry.get("total_score") or entry.get("synergy_score")
        syn = entry.get("synergy_score")
        part = f"{i}) {_ru_list(names)}"
        if score is not None:
            part += f" — score {score}"
        if syn is not None:
            part += f", синергия {syn}%"
        lines.append(part)
    lines.append("Варианты собраны конструктором Ghosteek.")
    return "\n".join(lines)


def _compose_meta(data: dict[str, Any]) -> str:
    decks = data.get("decks") or []
    lines = ["Топ меты (из meta-сервиса):"]
    for i, d in enumerate(decks[:5], start=1):
        cards = d.get("cards") or []
        names = [c if isinstance(c, str) else c.get("name") for c in cards]
        names = [n for n in names if n]
        wr = d.get("winrate")
        usage = d.get("usage")
        extra = []
        if wr is not None:
            extra.append(f"WR {wr}")
        if usage is not None:
            extra.append(f"usage {usage}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        title = d.get("name")
        head = f"{i}) {title}: " if title else f"{i}) "
        lines.append(f"{head}{_ru_list(names)}{suffix}")
    return "\n".join(lines)


def _compose_last_battle(data: dict[str, Any]) -> str:
    result = "Победа" if data.get("won") else "Поражение"
    lines = [
        f"{result} vs {data.get('opponent_name')}.",
        f"Матчап: {data.get('matchup_score')}/100.",
    ]
    if data.get("outcome_summary"):
        lines.append(str(data["outcome_summary"]))
    md = data.get("match_difficulty") or {}
    if md:
        lines.append(f"Сложность: {md.get('difficulty')}/100 — {md.get('rating')}.")
        for r in (md.get("reasons") or [])[:2]:
            lines.append(f"• {r}")
    mp = data.get("match_plan") or {}
    if mp.get("win_condition_window"):
        lines.append(f"Окно атаки: {mp['win_condition_window']}")
    for r in (data.get("reasons") or [])[:3]:
        if r and r not in lines:
            lines.append(str(r))
    lines.append("Полный разбор — в истории боёв.")
    return "\n".join(lines)


def _compose_matchup(data: dict[str, Any]) -> str:
    lines = [
        f"Ваша колода: {_ru_list(data.get('user_deck') or [])}.",
        f"Соперник: {_ru_list(data.get('opponent_deck') or [])}.",
        f"Оценка матчапа: {data.get('score')}/100 — {data.get('rating')}.",
    ]
    for r in (data.get("reasons") or [])[:4]:
        lines.append(f"• {r}")
    return "\n".join(lines)
