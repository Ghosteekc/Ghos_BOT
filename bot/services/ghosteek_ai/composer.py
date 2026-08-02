"""Сборка ответа игроку: данные сервисов + голос тренера Ghosteek AI."""

from __future__ import annotations

from typing import Any

from bot.services.card_names_ru import card_name_ru
from bot.services.ghosteek_ai.intents import (
    INTENT_ANALYZE_DECK,
    INTENT_BUILD_DECK,
    INTENT_CARD_INFO,
    INTENT_EXPLAIN_MECHANIC,
    INTENT_GAME_COACH,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    INTENT_MATCHUP,
)
from bot.services.ghosteek_ai.voice import assert_coach_voice, coach_reply


def _ru_list(cards: list[str], *, limit: int = 8) -> str:
    return ", ".join(card_name_ru(c, short=True) for c in cards[:limit])


def _first(*candidates: Any) -> str:
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
        if isinstance(c, list) and c:
            item = c[0]
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                msg = item.get("message") or item.get("text")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
    return ""


def compose_answer(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        err = str(payload.get("error") or "Пока не хватает данных для точного совета.")
        return assert_coach_voice(err)

    intent = payload.get("intent")
    data = payload.get("data") or {}

    if intent == INTENT_CARD_INFO:
        text = _compose_card(data)
    elif intent == INTENT_EXPLAIN_MECHANIC:
        text = _compose_mechanic(data)
    elif intent == INTENT_GAME_COACH:
        text = _compose_coach(data)
    elif intent in {INTENT_ANALYZE_DECK, INTENT_IMPROVE_DECK}:
        text = _compose_recommendation(intent, data)
    elif intent == INTENT_BUILD_DECK:
        text = _compose_build(data)
    elif intent == INTENT_LAST_BATTLE:
        text = _compose_last_battle(data)
    elif intent == INTENT_MATCHUP:
        text = _compose_matchup(data)
    else:
        text = coach_reply("Готово.", tip="Если нужно что-то ещё — скажи конкретнее.")

    return assert_coach_voice(text)


def _compose_card(data: dict[str, Any]) -> str:
    name = data.get("name_ru") or data.get("name") or "Карта"
    elixir = data.get("elixir")
    roles = ", ".join(data.get("roles") or []) or "универсальная"
    card_type = data.get("card_type") or "карта"
    return coach_reply(
        f"{name} — {elixir} эликсира, {card_type}.",
        why=f"В колоде она обычно работает как: {roles}.",
        action="Смотри, с чем она синергирует в твоей колоде, а не только «сильная ли карта сама по себе».",
        tip="Точный урон и HP в бою в данных нет — опирайся на роль и матчапы.",
    )


def _compose_mechanic(data: dict[str, Any]) -> str:
    ready = data.get("answer")
    if isinstance(ready, str) and ready.strip():
        return assert_coach_voice(ready.strip())
    title = str(data.get("title") or "Термин")
    summary = str(data.get("summary") or "")
    example = str(data.get("example") or "")
    tip = str(data.get("tip") or "")
    lines = [f"{title} — {summary}"]
    if example:
        lines.append(f"Пример: {example}")
    if tip:
        lines.append(tip)
    return assert_coach_voice("\n\n".join(lines))


def _compose_coach(data: dict[str, Any]) -> str:
    topic = data.get("topic")
    if topic == "climb":
        tips = [str(t) for t in (data.get("tips") or []) if t][:3]
        why = tips[0] if tips else "Стабильность важнее постоянной смены колод."
        action = tips[1] if len(tips) > 1 else "Закрепи одну колоду и разбери слабые бои."
        tip = tips[2] if len(tips) > 2 else "После серии поражений сначала разбор боя, потом замены."
        return coach_reply(
            "Кубки растут от стабильной колоды и спокойных решений, не от паники.",
            why=why,
            action=action,
            tip=tip,
        )

    rating = data.get("rating") or "спорный"
    score = data.get("score")
    arch = data.get("archetype") or "этот архетип"
    reason = _first(data.get("reasons"), data.get("disadvantages"), data.get("advantages"))
    action = _first(data.get("advantages"), data.get("reasons"))
    return coach_reply(
        f"Против «{arch}» матчап {rating}"
        + (f" ({score}/100)." if score is not None else "."),
        why=reason or f"Ориентир — эталонная колода «{arch}».",
        action=action or "Держи ответы на win condition и не отдавай бесплатный эликсир у моста.",
        tip="Если хочешь точный план под свой последний бой с этим архетипом — разберём его отдельно.",
    )


def _compose_recommendation(intent: str, data: dict[str, Any]) -> str:
    deck = data.get("deck") or []
    rec = data.get("recommendation") or {}
    coaching = rec.get("coaching") or {}
    gp = rec.get("game_plan") or {}
    plan = rec.get("improvement_plan") or {}
    synergy = data.get("synergy_score")
    style = coaching.get("play_style")
    strength = _first(coaching.get("strengths"), data.get("synergy_notes"))
    weakness = _first(gp.get("critical_weaknesses"), (rec.get("balance_issues") or {}).get("messages"))
    how = gp.get("how_to_win") or ""
    tip = _first(coaching.get("usage_tips"), data.get("synergy_notes"))

    if intent == INTENT_IMPROVE_DECK:
        if plan.get("needed"):
            step = _first(plan.get("steps"))
            return coach_reply(
                "Колоду можно усилить точечной заменой.",
                why=step or weakness or "Есть слабое место в балансе или синергии.",
                action=step or "Сначала закрой самую большую дыру, не меняй всё сразу.",
                tip=tip or "После замены сыграй пачку боёв и снова разберём.",
            )
        return coach_reply(
            "Критичных замен сейчас не нужно.",
            why=strength or (f"Синергия около {synergy}%." if synergy is not None else "Состав выглядит цельным."),
            action=how or "Играй чище по плану колоды — это даст больше, чем лишние свапы.",
            tip=tip or "Если матчап бесит — разберём конкретный бой, а не всю колоду заново.",
        )

    verdict = "Колода читается."
    if style:
        verdict = f"Играй это как {style}."
    elif synergy is not None:
        verdict = f"Колода собрана — синергия около {synergy}%."

    return coach_reply(
        verdict,
        why=strength or (f"Синергия {synergy}%." if synergy is not None else "Состав держится на своих сильных связках."),
        action=how or weakness or "Дави своим win condition, не разменивайся в минус без причины.",
        tip=tip or "В следующем бою следи за одним навыком — цикл или трейды.",
    )


def _compose_build(data: dict[str, Any]) -> str:
    core = data.get("core") or []
    decks = data.get("decks") or []
    mode = data.get("mode")
    if not decks:
        return coach_reply(
            "Пока не собрал вариантов.",
            why="Мало данных по ядру.",
            action="Дай win condition или 4 карты ядра.",
            tip="Пример: «хочу играть через Хога» или 4 карты подряд.",
        )

    first = decks[0]
    cards = first.get("cards") or first.get("card_names") or []
    if isinstance(cards, list) and cards and isinstance(cards[0], dict):
        names = [c.get("name") for c in cards if c.get("name")]
    else:
        names = [c for c in cards if isinstance(c, str)]
    title = first.get("name")
    label = title or _ru_list(names)
    core_txt = _ru_list(core, limit=4) if core else ""

    more = ""
    if len(decks) > 1:
        second = decks[1].get("name") or _ru_list(
            [c if isinstance(c, str) else c.get("name") for c in (decks[1].get("cards") or []) if c][:8]
        )
        more = f"Запасной вариант: {second}."

    if mode == "meta_templates":
        return coach_reply(
            f"Бери за основу «{label}».",
            why=f"Это готовый шаблон под {core_txt or 'твой win condition'}."
            if core_txt
            else "Это проверенный шаблон под твой win condition.",
            action=f"Состав: {_ru_list(names)}.",
            tip=more or "Если хочешь точную сборку под арену — пришли 4 карты ядра.",
        )

    return coach_reply(
        f"Собрал вариант: {_ru_list(names)}.",
        why=f"Ядро {core_txt} закрыто сборкой." if core_txt else "Сборка вокруг твоего ядра.",
        action="Протестируй 10–15 боёв, потом точечно улучшим.",
        tip=more or "Не меняй половину карт после двух поражений.",
    )


def _compose_last_battle(data: dict[str, Any]) -> str:
    won = data.get("won")
    opp = data.get("opponent_name") or "соперник"
    verdict = f"Победа против {opp}." if won else f"Поражение против {opp}."
    why = _first(
        data.get("outcome_summary"),
        data.get("reasons"),
        ((data.get("match_difficulty") or {}).get("reasons")),
    )
    if not why and data.get("matchup_score") is not None:
        why = f"Матчап был около {data.get('matchup_score')}/100."
    mp = data.get("match_plan") or {}
    action = mp.get("win_condition_window") or _first(data.get("reasons"))
    avoid = mp.get("avoid") or []
    tip = f"Не делай так: {avoid[0]}." if avoid else "Открой полный разбор в истории и повтори один ключевой момент."
    return coach_reply(
        verdict,
        why=why or "Ключевой момент боя уже в разборе.",
        action=action or "В следующем таком матчапе держи план из разбора.",
        tip=tip,
    )


def _compose_matchup(data: dict[str, Any]) -> str:
    rating = data.get("rating") or "спорный"
    score = data.get("score")
    reason = _first(data.get("reasons"), data.get("disadvantages"))
    action = _first(data.get("advantages"), data.get("reasons"))
    tip = _first(
        (data.get("reasons") or [None, None])[1:] if isinstance(data.get("reasons"), list) else None,
        data.get("disadvantages"),
    )
    return coach_reply(
        f"Матчап {rating}" + (f" ({score}/100)." if score is not None else "."),
        why=reason or "Смотри на win condition соперника и твои ответы.",
        action=action or "Не лезь в лобовую, если у врага готовый ответ.",
        tip=tip or "Подожди розыгрыша ключевой защиты — потом дави win condition.",
    )
