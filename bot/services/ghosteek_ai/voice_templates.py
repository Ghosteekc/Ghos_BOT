"""Шаблоны ответов Ghosteek AI по intent — только стиль, без доменной логики."""

from __future__ import annotations

from typing import Any

from bot.services.card_names_ru import card_name_ru
from bot.services.deck_sanity_validator import sanity_payload_from_data
from bot.services.ghosteek_ai.deck_card import extract_deck_names
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
    names = [card_name_ru(c, short=True) for c in cards[:limit] if c]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} и {names[1]}"
    return ", ".join(names[:-1]) + f" и {names[-1]}"


def _core_names(data: dict[str, Any], *, limit: int = 4) -> list[str]:
    raw = data.get("core") or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name") or item.get("card")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
        if len(out) >= limit:
            break
    return out


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
    """Честный вердикт по колоде игрока — без канцелярита и без «доделай сам»."""
    msgs = [str(m) for m in (sanity.get("critical_messages") or []) if m]
    verdict = str(sanity.get("coach_verdict") or "").strip()
    if not verdict:
        verdict = msgs[0] if msgs else "В этой колоде пока не хватает устойчивого плана."
    why = str(sanity.get("coach_why") or "").strip()
    if not why and len(msgs) >= 2:
        why = msgs[1]
    if not why:
        why = "По составу видно дыру — давай закроем её заменой, а не оправданиями."
    return coach_reply(
        verdict,
        why=why,
        tip="Могу сразу предложить, что поменять.",
        intent=intent,
        archetype=arch,
    )


def template_build_deck(data: dict[str, Any]) -> str:
    core = _core_names(data)
    decks = data.get("decks") or []
    mode = data.get("mode")
    stage = data.get("stage") or mode
    arch = _arch_from_data(data)
    label = archetype_label(arch)
    tip = ""
    core_txt = _ru_list(core, limit=4) if core else ""
    multi_core = len(core) > 1

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
    first = decks[0] if isinstance(decks[0], dict) else {}
    complete = len(extract_deck_names(first)) >= 8
    # Готовая 8-карта — это уже предложение игроку, а не черновик «доделай сам».
    if sanity is not None and not sanity.get("passed", True) and not complete:
        return _template_sanity_fail(sanity, intent=INTENT_BUILD_DECK, arch=arch)

    title = first.get("name") or arch or label
    alt = ""
    if len(decks) > 1 and isinstance(decks[1], dict):
        alt_name = decks[1].get("name") or decks[1].get("archetype")
        if alt_name:
            alt = f"Ещё вариант — {archetype_label(str(alt_name))}."
    multi_decks = sum(1 for d in decks if isinstance(d, dict)) > 1

    if mode == "meta_templates" or stage == "meta_templates":
        if multi_core and core_txt:
            why = f"Играется через {core_txt}, цикл держит темп."
        elif core_txt:
            why = f"Играется через {core_txt}, цикл держит темп."
        else:
            why = f"Стиль — {label}."
        return coach_reply(
            f"Собрал {title} — можно сразу ставить." if title else f"Собрал {label}.",
            why=why,
            tip=alt or tip,
            intent=INTENT_BUILD_DECK,
            archetype=arch,
        )

    if mode in {"freeform_anchor", "archetype_fallback"} or stage in {
        "freeform_anchor",
        "archetype_fallback",
    }:
        style = label or "контроль"
        if multi_core and core_txt:
            verdict = f"Собрал {style.lower()} вокруг {core_txt}."
            why = "Все запрошенные карты в составе — под них закрыл поддержку, спеллы и цикл."
        elif core_txt:
            verdict = f"Собрал {style.lower()} вокруг {core_txt}."
            why = "Под неё закрыл поддержку, спеллы и цикл — колода уже полная."
        else:
            verdict = f"Собрал рабочий {style.lower()}."
            why = "Роли закрыты, можно пробовать на лестнице."
        if multi_decks:
            verdict = f"Собрал {sum(1 for d in decks if isinstance(d, dict))} варианта вокруг {core_txt or style.lower()}."
            why = "Ядро то же, поддержка и цикл отличаются — выбирай, что ближе по стилю."
        return coach_reply(
            verdict,
            why=why,
            tip=alt or tip,
            intent=INTENT_BUILD_DECK,
            archetype=arch,
        )

    verdict = f"Собрал {title}." if title else f"Собрал {label}."
    if core_txt:
        why = f"Опора {core_txt} уже в составе — это готовый вариант, не черновик."
    else:
        why = f"Сборка держится на ролях под {label}."
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
    # Tip только из ToolResult; не дублируем why и не тянем coach_tips.json.
    tip = ""

    if improve:
        if plan.get("needed"):
            step = _first(plan.get("steps"))
            return coach_reply(
                "Есть точечная замена — полную пересборку не трогаем.",
                why=step or weakness or "Есть дыра в ролях или связках.",
                tip=tip,
                intent=intent,
                archetype=arch if isinstance(arch, str) else None,
            )
        return coach_reply(
            "Критических замен не вижу.",
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
    # Факты из evaluate_matchup — не выдумываем tip поверх.
    reason = _first(
        data.get("reasons"),
        data.get("advantages"),
        data.get("disadvantages"),
    )
    adv = data.get("advantages") or []
    tip = ""
    if isinstance(adv, list) and adv and isinstance(adv[0], str) and adv[0].strip():
        tip = adv[0].strip()
    if not tip:
        tip = reason or ""

    hard = rating.lower() in {"сложный", "hard", "плохой", "невыгодный"}
    easy = rating.lower() in {"лёгкий", "легкий", "easy", "хороший", "выгодный"}
    if hard:
        verdict = "Матчап сложный."
    elif easy:
        verdict = "Матчап удобный."
    else:
        verdict = "Матчап спорный."

    why = reason or "Точного вывода по этому матчапу недостаточно — смотри состав и ключевые контры."
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

    if any(str(r).lower() in ("air_defense", "air") for r in roles):
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
    window = str(mp.get("win_condition_window") or "").strip()
    # Tip из фактов плана (ошибка / окно), не из универсального coach_tips.
    tip_raw = avoid[0] if avoid and isinstance(avoid[0], str) else ""
    tip = tip_raw.strip() if tip_raw else window
    if not tip or tip.lower().startswith("в похожем"):
        tip = ""
    # Не дублируем why тем же текстом, что уже в verdict
    if why and won is False and "рано" in why.lower() and "атак" in why.lower():
        why = "До двойного эликсира играй спокойнее."
        if tip.lower() in why.lower() or "рано" in tip.lower():
            tip = window or ""

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
            tip=tips[1] if len(tips) > 1 else "",
            intent=INTENT_GAME_COACH,
            archetype="Meta",
        )

    arch = data.get("archetype") or "этот архетип"
    rating = data.get("rating") or "спорный"
    reason = _first(data.get("reasons"), data.get("disadvantages"), data.get("advantages"))
    return coach_reply(
        f"Против «{archetype_label(str(arch))}» матчап {rating}.",
        why=reason or "Не отдавай эликсир у моста и держи ответ на их вин-кондишн.",
        tip=_first(data.get("advantages"), data.get("reasons")) or "",
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
    tip = str(data.get("tip") or "")
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
        "NO_VALID_BUILD": (
            params.get("reason")
            or "Не удалось собрать стабильную колоду вокруг выбранных карт.",
            params.get("suggestion")
            or "Добавьте спелл / поддержку в ядро или смените главную угрозу.",
            "Могу попробовать с другим набором карт.",
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
