"""Шаблоны ответов Ghosteek AI по intent — только стиль, без доменной логики."""

from __future__ import annotations

from typing import Any

from bot.services.card_names_ru import card_name_ru
from bot.services.deck_sanity_validator import sanity_payload_from_data
from bot.services.ghosteek_ai.coach_tips import pick_tip
from bot.services.ghosteek_ai.glossary import archetype_label
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


def _ru_list(cards: list[str], *, limit: int = 4) -> str:
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


def re_has_score(text: str) -> bool:
    import re

    return bool(re.search(r"\d+\s*/\s*100|\d+\s*%", text or ""))


def _arch_from_data(data: dict[str, Any]) -> str | None:
    first = None
    decks = data.get("decks")
    if isinstance(decks, list) and decks and isinstance(decks[0], dict):
        first = decks[0]
    for src in (first, data, data.get("recommendation") or {}):
        if not isinstance(src, dict):
            continue
        for key in ("archetype", "category", "name"):
            val = src.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


# ---------------------------------------------------------------------------
# Intent templates
# ---------------------------------------------------------------------------


def _template_sanity_fail(sanity: dict[str, Any], *, intent: str, arch: str | None) -> str:
    """Честный вердикт тренера — без оправдания Builder и без плана игры."""
    msgs = [str(m) for m in (sanity.get("critical_messages") or []) if m]
    verdict = str(sanity.get("coach_verdict") or "").strip()
    if not verdict:
        verdict = msgs[0] if msgs else "Эта сборка выглядит нестабильной. Я бы пересобрал её."
    why = str(sanity.get("coach_why") or "").strip()
    if not why and len(msgs) >= 2:
        why = msgs[1]
    if not why:
        why = "Builder мог ошибиться — не буду оправдывать слабую сборку."
    return coach_reply(
        verdict,
        why=why,
        tip="Сначала закрой критические дыры, потом разберём, как ей играть.",
        intent=intent,
        archetype=arch,
    )


def template_build_deck(data: dict[str, Any]) -> str:
    core = data.get("core") or []
    decks = data.get("decks") or []
    mode = data.get("mode")
    stage = data.get("stage") or mode
    arch = _arch_from_data(data)
    label = archetype_label(arch)
    tip = pick_tip(arch, seed=str(arch or core))
    primary = core[0] if core else None
    primary_ru = card_name_ru(primary, short=True) if primary else ""

    if not decks:
        # Пустой список — внутренняя ошибка; не светим шаблоны/ядро пользователю.
        return coach_reply(
            "Уточни, через какую карту собираем.",
            why="Нужна хотя бы одна опора для стиля.",
            tip="Напиши, например: «собери колоду через ГигСкелета».",
            intent=INTENT_BUILD_DECK,
            archetype=arch,
        )

    sanity = sanity_payload_from_data(data)
    if sanity is not None and not sanity.get("passed", True):
        return _template_sanity_fail(sanity, intent=INTENT_BUILD_DECK, arch=arch)

    first = decks[0] if isinstance(decks[0], dict) else {}
    title = first.get("name") or arch or label
    alt = ""
    if len(decks) > 1 and isinstance(decks[1], dict):
        alt_name = decks[1].get("name") or decks[1].get("archetype")
        if alt_name:
            alt = f"Запасной вариант — {archetype_label(str(alt_name))}."

    if mode == "meta_templates" or stage == "meta_templates":
        return coach_reply(
            f"Собрал {title}." if title else f"Собрал {label}.",
            why=f"Стиль держится на {primary_ru}." if primary_ru else f"Стиль — {label}.",
            tip=alt or tip,
            intent=INTENT_BUILD_DECK,
            archetype=arch,
        )

    if mode in {"freeform_anchor", "archetype_fallback"} or stage in {
        "freeform_anchor",
        "archetype_fallback",
    }:
        style = label or "контроль"
        if primary_ru:
            verdict = f"Собрал {style.lower()} вокруг {primary_ru}."
            why = f"Добавил поддержку, спеллы и цикл под {primary_ru}."
        else:
            verdict = f"Собрал рабочий {style.lower()}."
            why = "Закрыл роли под выбранный стиль."
        return coach_reply(
            verdict,
            why=why,
            tip=alt or tip,
            intent=INTENT_BUILD_DECK,
            archetype=arch,
        )

    core_txt = _ru_list(core, limit=4) if core else ""
    verdict = f"Собрал {title}." if title else f"Собрал {label}."
    why = (
        f"Ядро {core_txt} закрыто ролями."
        if core_txt
        else f"Сборка держится на ролях под {label}."
    )
    # Не используем слово «ядро» в пользовательском why — перефразируем.
    if core_txt:
        why = f"Опора {core_txt} закрыта ролями."
    return coach_reply(
        verdict,
        why=why,
        tip=alt or tip,
        intent=INTENT_BUILD_DECK,
        archetype=arch,
    )


def template_analyze_deck(data: dict[str, Any], *, improve: bool = False) -> str:
    rec = data.get("recommendation") or {}
    coaching = rec.get("coaching") or {}
    gp = rec.get("game_plan") or {}
    plan = rec.get("improvement_plan") or {}
    arch = (
        (rec.get("intent") or {}).get("archetype")
        if isinstance(rec.get("intent"), dict)
        else None
    ) or data.get("archetype")
    intent = INTENT_IMPROVE_DECK if improve else INTENT_ANALYZE_DECK

    sanity = sanity_payload_from_data(data)
    if sanity is not None and not sanity.get("passed", True) and not improve:
        # Анализ: сначала честные дыры, без «как играть».
        return _template_sanity_fail(
            sanity,
            intent=intent,
            arch=arch if isinstance(arch, str) else None,
        )

    strength = _first(coaching.get("strengths"), data.get("synergy_notes"))
    weakness = _first(
        gp.get("critical_weaknesses"),
        (rec.get("balance_issues") or {}).get("messages"),
    )
    how = gp.get("how_to_win") or ""
    tip = pick_tip(arch if isinstance(arch, str) else None, seed=strength or weakness)

    if improve:
        if plan.get("needed"):
            step = _first(plan.get("steps"))
            return coach_reply(
                "Нужна точечная замена, не пересборка.",
                why=step or weakness or "Есть дыра в ролях или связках.",
                tip=tip,
                intent=intent,
                archetype=arch if isinstance(arch, str) else None,
            )
        return coach_reply(
            "Критических замен нет.",
            why=strength or how or "Состав уже держится.",
            tip=tip,
            intent=intent,
            archetype=arch if isinstance(arch, str) else None,
        )

    style = coaching.get("play_style")
    label = archetype_label(arch if isinstance(arch, str) else None)
    verdict = f"Играй это как {style}." if style else f"Состав читается как {label}."
    return coach_reply(
        verdict,
        why=strength or how or weakness or "Держись своего темпа и вин-кондишна.",
        tip=tip,
        intent=intent,
        archetype=arch if isinstance(arch, str) else None,
    )


def template_matchup(data: dict[str, Any]) -> str:
    rating = str(data.get("rating") or "спорный").strip()
    # Не повторяем проценты/score — их покажет карточка, если будет.
    reason = _first(data.get("reasons"), data.get("disadvantages"))
    tip = pick_tip(data.get("archetype") if isinstance(data.get("archetype"), str) else None)

    hard = rating.lower() in {"сложный", "hard", "плохой", "невыгодный"}
    easy = rating.lower() in {"лёгкий", "легкий", "easy", "хороший", "выгодный"}
    if hard:
        verdict = "Матчап сложный."
    elif easy:
        verdict = "Матчап удобный."
    else:
        verdict = "Матчап спорный."

    why = reason or "Главное — не отдавать преимущество по эликсиру."
    return coach_reply(
        verdict,
        why=why,
        tip=tip,
        intent=INTENT_MATCHUP,
    )


def template_card_info(data: dict[str, Any]) -> str:
    name = data.get("name_ru") or data.get("name") or "Карта"
    elixir = data.get("elixir")
    roles_raw = data.get("roles") or []
    roles = [str(r) for r in roles_raw if r] if isinstance(roles_raw, list) else []
    cost = f"за {elixir} эликсира" if elixir is not None else "в своём косте"

    if any("воздух" in r.lower() or "air" in r.lower() for r in roles):
        verdict = f"{name} — универсальная защита {cost}."
        why = "Хорошо останавливает воздух и помогает пережить давление."
    elif roles:
        role_txt = ", ".join(roles[:2])
        verdict = f"{name} — {role_txt} {cost}."
        why = "Закрывает свою роль и помогает держать темп боя."
    else:
        verdict = f"{name} — универсальная карта {cost}."
        why = "Смотри не силу саму по себе, а какой трейд она закрывает."

    return coach_reply(
        verdict,
        why=why,
        tip=f"Не трать их в начале боя без необходимости.",
        intent=INTENT_CARD_INFO,
    )


def template_battle(data: dict[str, Any]) -> str:
    won = data.get("won")
    why = _first(
        data.get("outcome_summary"),
        data.get("reasons"),
        ((data.get("match_difficulty") or {}).get("reasons")),
    )
    if why and re_has_score(why):
        why = ""
    mp = data.get("match_plan") or {}
    avoid = mp.get("avoid") or []
    tip_raw = avoid[0] if avoid and isinstance(avoid[0], str) else ""
    tip = tip_raw.strip() if tip_raw else pick_tip(None, seed=str(won))
    if tip.lower().startswith("в похожем"):
        tip = pick_tip(None, seed="battle")
    # Не дублируем why тем же текстом, что уже в verdict
    if why and won is False and "рано" in why.lower() and "атак" in why.lower():
        why = "До двойного эликсира играй спокойнее."
        if tip.lower() in why.lower() or "рано" in tip.lower():
            tip = pick_tip(None, seed="loss")

    if won:
        verdict = "Ключ победы — контроль темпа."
        explanation = why or "Ты не отдал лишний эликсир и закрыл их вин-кондишн."
    else:
        verdict = "Главная ошибка — слишком ранний выход в атаку."
        explanation = why or "До двойного эликсира играй спокойнее."

    return coach_reply(
        verdict,
        why=explanation,
        tip=tip,
        intent=INTENT_LAST_BATTLE,
    )


def template_game_coach(data: dict[str, Any]) -> str:
    topic = data.get("topic")
    if topic == "climb":
        tips = [str(t) for t in (data.get("tips") or []) if t]
        return coach_reply(
            "Кубки растут от стабильных решений.",
            why=tips[0] if tips else "Одна колода лучше постоянной смены.",
            tip=tips[1] if len(tips) > 1 else pick_tip("Meta"),
            intent=INTENT_GAME_COACH,
            archetype="Meta",
        )

    arch = data.get("archetype") or "этот архетип"
    rating = data.get("rating") or "спорный"
    reason = _first(data.get("reasons"), data.get("disadvantages"), data.get("advantages"))
    return coach_reply(
        f"Против «{archetype_label(str(arch))}» матчап {rating}.",
        why=reason or "Не отдавай эликсир у моста и держи ответ на их вин-кондишн.",
        tip=pick_tip(str(arch), seed=str(arch)),
        intent=INTENT_GAME_COACH,
        archetype=str(arch),
    )


def template_mechanic(data: dict[str, Any]) -> str:
    ready = data.get("answer")
    if isinstance(ready, str) and ready.strip():
        # Ужимаем готовый текст словаря под формат тренера
        return assert_coach_voice(ready.strip())
    title = str(data.get("title") or "Термин")
    summary = str(data.get("summary") or "")
    tip = str(data.get("tip") or "") or pick_tip(None, seed=title)
    return coach_reply(
        f"{title} — {summary}" if summary else f"{title}.",
        why=str(data.get("example") or "").strip(),
        tip=tip,
        intent=INTENT_EXPLAIN_MECHANIC,
    )


def template_knowledge(data: dict[str, Any]) -> str:
    """Общий knowledge fallback (если нет отдельного mechanic answer)."""
    return template_mechanic(data)


def template_error(code: str, params: dict[str, Any] | None = None) -> str | None:
    """Короткие ошибки. None = пусть caller возьмёт clarify."""
    params = params or {}

    mapping: dict[str, tuple[str, str, str]] = {
        "NEED_CARD_NAME": (
            "Какую карту разбираем?",
            "Нужно точное название.",
            "Напиши, например: «что делает Палач».",
        ),
        "NEED_DECK_8": (
            "Нужна колода из 8 карт.",
            "Без состава совет будет пустым.",
            "Пришли карты или привяжи тег.",
        ),
        "NO_BATTLES": (
            "Истории боёв пока нет.",
            "Без боя разбирать нечего.",
            "Синхронизируй бои после матча.",
        ),
        "MATCHUP_NEED_DECKS": (
            "Для матчапа мало данных.",
            "Нужны две колоды или бой в истории.",
            "Пришли составы или синхронизируй бой.",
        ),
        "BUILD_NEED_CORE": (
            "Через какую карту собираем?",
            "Нужна опора для стиля.",
            "Напиши, например: «собери через ГигСкелета».",
        ),
        "BUILD_NEED_CARD": (
            "Через какую карту собираем?",
            "Нужна опора для стиля.",
            "Напиши, например: «собери через Хога».",
        ),
        "BUILD_UNKNOWN_CARD": (
            f"Карту «{params.get('card_ru') or 'эту'}» не узнаю.",
            "Без точного названия собрать нельзя.",
            "Проверь написание или пришли другое имя.",
        ),
        "BUILD_IMPOSSIBLE": (
            "С этой опорой сейчас не собрать рабочий состав.",
            "Скорее всего карта недоступна в пуле.",
            "Попробуй другую ключевую карту.",
        ),
        # Legacy codes — никогда не светим шаблоны/ядро пользователю.
        "BUILD_NO_VARIANTS": (
            "Через какую карту усилим сборку?",
            "Нужна более ясная опора.",
            "Напиши win-condition или ключевую карту.",
        ),
        "BUILD_NO_TEMPLATES": (
            "Через какую карту собираем?",
            "Нужна опора для стиля.",
            "Напиши, например: «собери через ГигСкелета».",
        ),
        "COACH_NEED_ARCHETYPE": (
            "Против кого готовимся?",
            "Нужен конкретный архетип.",
            "Напиши, например: «против хог-цикла».",
        ),
        "COACH_NEED_DECK": (
            f"Против «{params.get('archetype') or 'этого архетипа'}» нужен твой состав.",
            "Без колоды совет будет общим.",
            "Пришли колоду или привяжи тег.",
        ),
        "COACH_CLARIFY": (
            "Уточни совет.",
            "Нужна одна цель.",
            "«Как апнуть кубки?» или «как играть против лавалуна?»",
        ),
    }
    if code not in mapping:
        return None
    verdict, why, tip = mapping[code]
    intent = "build_deck" if code.startswith("BUILD_") else "clarify"
    return coach_reply(verdict, why=why, tip=tip, intent=intent)
