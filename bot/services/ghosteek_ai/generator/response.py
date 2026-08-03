"""Template Response Generator — сейчас шаблоны; позже Qwen.

Получает только AIContext. Не знает, как работают доменные сервисы.
"""

from __future__ import annotations

from typing import Any

from bot.services.card_names_ru import card_name_ru
from bot.services.ghosteek_ai.constraints import refuse_unsupported
from bot.services.ghosteek_ai.intents import (
    CLARIFY_PROMPT,
    INTENT_ANALYZE_DECK,
    INTENT_BUILD_DECK,
    INTENT_CARD_INFO,
    INTENT_EXPLAIN_MECHANIC,
    INTENT_GAME_COACH,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    INTENT_MATCHUP,
)
from bot.services.ghosteek_ai.models import AIContext
from bot.services.ghosteek_ai.voice import assert_coach_voice, coach_reply


def _ru_list(cards: list[str], *, limit: int = 8) -> str:
    return ", ".join(card_name_ru(c, short=True) for c in cards[:limit])


def _truncate_q(text: str, limit: int = 64) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


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


class TemplateResponseGenerator:
    """Генерация ответа из AIContext через coach-шаблоны.

    Реализует ResponseGenerator Protocol.
    Alias: TemplateGenerator.

    TODO(Qwen): рядом QwenResponseGenerator; factory переключает backend.
    Модель не подключать в этом классе.
    """

    backend = "template"

    def generate(self, ctx: AIContext) -> str:
        if not ctx.ok:
            return assert_coach_voice(self._from_error(ctx))
        text = self._from_success(ctx)
        return assert_coach_voice(text)

    def _from_error(self, ctx: AIContext) -> str:
        code = ctx.error_code or "CLARIFY"
        params = ctx.error_params or {}

        if code == "UNSUPPORTED":
            return refuse_unsupported()

        if code in {"CLARIFY", "META_NOT_READY", "STATS_NOT_READY"}:
            return self._clarify_with_memory(ctx)

        if code == "NEED_CARD_NAME":
            return coach_reply(
                "Какую карту разбираем?",
                action="Напиши, например: «что делает Палач».",
                tip="Тогда дам роль и как её обычно ставят в колоду.",
            )

        if code == "UNKNOWN_MECHANIC":
            titles = params.get("suggestions") or []
            titles_txt = ", ".join(titles) if isinstance(titles, list) else ""
            return coach_reply(
                "Этого термина в словаре пока нет.",
                why="Не буду выдумывать определение.",
                action=f"Могу объяснить, например: {titles_txt}."
                if titles_txt
                else "Напиши точное название — Cycle, Tempo, Overcommit.",
                tip="Напиши точное название — Cycle, Tempo, Overcommit и т.д.",
            )

        if code == "NEED_DECK_8":
            return coach_reply(
                "Нужна колода из 8 карт.",
                why="Без состава совет будет пустым.",
                action="Пришли названия карт или привяжи тег — возьму текущую колоду из профиля.",
                tip="Потом разберём или улучшим уже по факту.",
            )

        if code == "NO_BATTLES":
            return coach_reply(
                "Истории боёв пока нет.",
                why="Без боя разбирать нечего.",
                action="Синхронизируй бои или сыграй ladder/PvP.",
                tip="После этого разберём последний матч по шагам.",
            )

        if code == "MATCHUP_NEED_DECKS":
            return coach_reply(
                "Для матчапа мало данных.",
                why="Нужны две колоды по 8 карт или хотя бы один бой в истории.",
                action="Пришли обе колоды или сыграй бой и синхронизируй историю.",
                tip="Тогда скажу, где давить и где лучше подождать.",
            )

        if code == "BUILD_NEED_CORE":
            return coach_reply(
                "Чтобы собрать колоду, нужен ориентир.",
                why="Без win condition или ядра сборка будет гаданием.",
                action="Напиши «хочу играть через Хога» или 4 карты ядра.",
                tip="После этого дам готовый вариант под твой стиль.",
            )

        if code == "BUILD_NO_VARIANTS":
            return coach_reply(
                "Вокруг этого ядра пока не собрал стабильный вариант.",
                why="Конструктор не нашёл подходящую сборку.",
                action="Попробуй другое ядро из 4 карт или другой win condition.",
                tip="Пример: Хог, Терпила, Мушкетёр, Пушка.",
            )

        if code == "BUILD_NO_TEMPLATES":
            card_ru = params.get("card_ru") or "этой карты"
            return coach_reply(
                f"Готовых шаблонов вокруг «{card_ru}» нет.",
                why="Нет готовой колоды под эту опору.",
                action="Дай ядро из 4 карт — соберём точнее.",
                tip="Пример: «собери колоду вокруг Хог Терпила Мушкетёр Пушка».",
            )

        if code == "COACH_NEED_ARCHETYPE":
            return coach_reply(
                "Против кого готовимся?",
                why="Нужен конкретный архетип.",
                action="Напиши, например: «как играть против Lavaloon» или «против Хог 2.6».",
                tip="Тогда разберём план под твою колоду.",
            )

        if code == "COACH_NEED_DECK":
            arch = params.get("archetype") or "этот архетип"
            return coach_reply(
                f"Против «{arch}» нужен твой состав.",
                why="Без твоей колоды из 8 карт совет будет общим и пустым.",
                action="Пришли колоду или привяжи тег.",
                tip="Можно также разобрать матчап, если дашь обе колоды.",
            )

        if code == "COACH_CLARIFY":
            return coach_reply(
                "Уточни совет.",
                action="«Как апнуть кубки?» или «как играть против Lavaloon?»",
                tip="Чем конкретнее вопрос — тем точнее план.",
            )

        return CLARIFY_PROMPT

    def _clarify_with_memory(self, ctx: AIContext) -> str:
        """Clarify с опорой на summary / предыдущие вопросы — без угадывания."""
        prev_questions = list(ctx.last_questions[:-1]) if ctx.last_questions else []
        if ctx.conversation_summary or prev_questions:
            hint_parts: list[str] = []
            if prev_questions:
                last_q = prev_questions[-1]
                if last_q and last_q.strip():
                    hint_parts.append(f"Ранее ты спрашивал: «{_truncate_q(last_q)}».")
            if ctx.active_topic:
                hint_parts.append(f"Тема сессии: {ctx.active_topic}.")
            if ctx.conversation_summary:
                hint_parts.append("У меня есть краткое резюме нашего разговора.")
            tip = " ".join(hint_parts) if hint_parts else ""
            return coach_reply(
                "Давай сузим задачу.",
                why=tip or "Без конкретики получится общий совет — он почти не помогает в бою.",
                action="Могу: собрать колоду, разобрать состав, улучшить карты, "
                "разобрать матчап или бой, объяснить карту/механику, "
                "дать план по кубкам или против архетипа.",
                tip="Напиши одну цель: что улучшить прямо сейчас.",
            )
        return CLARIFY_PROMPT

    def _from_success(self, ctx: AIContext) -> str:
        intent = ctx.intent.request
        data = ctx.primary_tool_data()

        if intent == INTENT_CARD_INFO:
            return self._compose_card(ctx.knowledge.card or data)
        if intent == INTENT_EXPLAIN_MECHANIC:
            return self._compose_mechanic(ctx.knowledge.mechanic or data)
        if intent == INTENT_GAME_COACH:
            return self._compose_coach(ctx.knowledge.coach or data)
        if intent in {INTENT_ANALYZE_DECK, INTENT_IMPROVE_DECK}:
            return self._compose_recommendation(intent, data)
        if intent == INTENT_BUILD_DECK:
            return self._compose_build(ctx.build or data)
        if intent == INTENT_LAST_BATTLE:
            battle = ctx.battle.to_dict() if (ctx.battle.raw or ctx.battle.opponent_name) else data
            return self._compose_last_battle(battle)
        if intent == INTENT_MATCHUP:
            eval_data = ctx.evaluation.to_dict()
            merged = {**eval_data, **data} if eval_data.get("rating") or eval_data.get("score") is not None else data
            return self._compose_matchup(merged)
        return coach_reply(
            "Нужна чуть более конкретная задача.",
            tip="Напиши колоду, матчап, бой или термин — разберём по механике.",
        )

    def _compose_card(self, data: dict[str, Any]) -> str:
        name = data.get("name_ru") or data.get("name") or "Карта"
        elixir = data.get("elixir")
        roles = ", ".join(data.get("roles") or []) or "универсальная"
        card_type = data.get("card_type") or "карта"
        return coach_reply(
            f"{name} — {elixir} эликсира, {card_type}.",
            why=f"Её работа в колоде: {roles}. Смотри не «сила сама по себе», а какой трейд и роль она закрывает.",
            action="Проверь, есть ли у тебя ответ на то, что она бьёт, и синергия с win condition.",
            tip=f"В бою ставь {name} под задачу роли — не кидай «просто чтобы что-то сделать».",
        )

    def _compose_mechanic(self, data: dict[str, Any]) -> str:
        ready = data.get("answer")
        if isinstance(ready, str) and ready.strip():
            return assert_coach_voice(ready.strip())
        title = str(data.get("title") or "Термин")
        summary = str(data.get("summary") or "")
        example = str(data.get("example") or "")
        tip = str(data.get("tip") or "")
        return coach_reply(
            f"{title}: {summary}",
            why=f"Пример: {example}" if example else "",
            tip=tip or "В следующем бою назови момент, где это сработало или сломалось — так термин закрепится.",
        )

    def _compose_coach(self, data: dict[str, Any]) -> str:
        topic = data.get("topic")
        if topic == "climb":
            tips = [str(t) for t in (data.get("tips") or []) if t][:3]
            why = tips[0] if tips else "Стабильный цикл решений важнее постоянной смены колод."
            action = tips[1] if len(tips) > 1 else "Закрепи одну колоду и разбирай слабые матчапы точечно."
            tip = tips[2] if len(tips) > 2 else "После 3 поражений подряд — сначала разбор боя, потом замены."
            return coach_reply(
                "Кубки растут от стабильных решений, не от паники после двух лоссов.",
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
            why=reason or f"Ключ — ответы на win condition «{arch}» и контроль эликсира у моста.",
            action=action or "Не отдавай бесплатный эликсир у моста и не пускай их win condition без ответа.",
            tip="В следующем таком матче заранее реши, чем гасишь win condition — и не трать этот ответ раньше времени.",
        )

    def _compose_recommendation(self, intent: str, data: dict[str, Any]) -> str:
        rec = data.get("recommendation") or {}
        coaching = rec.get("coaching") or {}
        gp = rec.get("game_plan") or {}
        plan = rec.get("improvement_plan") or {}
        synergy = data.get("synergy_score")
        style = coaching.get("play_style")
        strength = _first(coaching.get("strengths"), data.get("synergy_notes"))
        weakness = _first(
            gp.get("critical_weaknesses"),
            (rec.get("balance_issues") or {}).get("messages"),
        )
        how = gp.get("how_to_win") or ""
        tip = _first(coaching.get("usage_tips"), data.get("synergy_notes"))

        if intent == INTENT_IMPROVE_DECK:
            if plan.get("needed"):
                step = _first(plan.get("steps"))
                return coach_reply(
                    "Усиление — точечная замена, не пересборка с нуля.",
                    why=step or weakness or "Есть дыра в балансе ролей или синергии.",
                    action=step or "Закрой самую большую дыру одной картой, остальное не трогай.",
                    tip=tip or "Сыграй 10–15 боёв на новой карте, потом снова разберём трейды.",
                )
            return coach_reply(
                "Критических замен сейчас нет.",
                why=strength
                or (f"Синергия около {synergy}% — состав цельный." if synergy is not None else "Состав уже держится."),
                action=how or "Выигрыш здесь в чистой игре по плану колоды, а не в свапах.",
                tip=tip or "Если бесит конкретный матчап — разберём бой, а не всю колоду.",
            )

        verdict = "Состав читается по ролям."
        if style:
            verdict = f"Играй это как {style}: свой темп, свой win condition."
        elif synergy is not None:
            verdict = f"Колода собрана — синергия около {synergy}%."

        return coach_reply(
            verdict,
            why=strength
            or (
                f"Синергия {synergy}% — связки есть."
                if synergy is not None
                else "Состав держится на своих сильных связках."
            ),
            action=how or weakness or "Дави win condition после плюса по эликсиру, не лезь в минус без причины.",
            tip=tip or "В следующем бою следи за одним навыком: цикл или трейды.",
        )

    def _compose_build(self, data: dict[str, Any]) -> str:
        core = data.get("core") or []
        decks = data.get("decks") or []
        mode = data.get("mode")
        if not decks:
            return coach_reply(
                "Пока не собрал вариантов.",
                why="Мало данных по ядру — без win condition сборка будет гаданием.",
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
                [
                    c if isinstance(c, str) else c.get("name")
                    for c in (decks[1].get("cards") or [])
                    if c
                ][:8]
            )
            more = f"Запасной вариант: {second}."

        if mode == "meta_templates":
            return coach_reply(
                f"Бери за основу «{label}».",
                why=f"Шаблон закрывает {core_txt or 'твой win condition'} готовыми ролями."
                if core_txt
                else "Это проверенный шаблон под твой win condition.",
                action=f"Состав: {_ru_list(names)}.",
                tip=more or "Сыграй пачку, потом точечно подкрутим ответы на твои проигрышные матчапы.",
            )

        return coach_reply(
            f"Собрал вариант: {_ru_list(names)}.",
            why=f"Ядро {core_txt} закрыто ролями." if core_txt else "Сборка вокруг твоего ядра.",
            action="Протестируй 10–15 боёв — смотри трейды, не только винрейт за вечер.",
            tip=more or "Не меняй половину карт после двух поражений.",
        )

    def _compose_last_battle(self, data: dict[str, Any]) -> str:
        won = data.get("won")
        opp = data.get("opponent_name") or "соперник"
        verdict = f"Победа против {opp}." if won else f"Поражение против {opp}."
        why = _first(
            data.get("outcome_summary"),
            data.get("reasons"),
            ((data.get("match_difficulty") or {}).get("reasons")),
        )
        if not why and data.get("matchup_score") is not None:
            why = f"Матчап был около {data.get('matchup_score')}/100 — это про давление составов, не про «рандом»."
        mp = data.get("match_plan") or {}
        action = mp.get("win_condition_window") or _first(data.get("reasons"))
        avoid = mp.get("avoid") or []
        tip = (
            f"В похожем матчапе не делай так: {avoid[0]}"
            if avoid
            else "Открой полный разбор и повтори один ключевой момент — цикл или ответ на WC."
        )
        return coach_reply(
            verdict,
            why=why or "Ключевой фактор уже в разборе по составу и счёту.",
            action=action or "В следующем таком матчапе заранее реши, чем гасишь их win condition.",
            tip=tip,
        )

    def _compose_matchup(self, data: dict[str, Any]) -> str:
        rating = data.get("rating") or "спорный"
        score = data.get("score")
        reason = _first(data.get("reasons"), data.get("disadvantages"))
        action = _first(data.get("advantages"), data.get("reasons"))
        tip = _first(
            (data.get("reasons") or [None, None])[1:]
            if isinstance(data.get("reasons"), list)
            else None,
            data.get("disadvantages"),
        )
        return coach_reply(
            f"Матчап {rating}" + (f" ({score}/100)." if score is not None else "."),
            why=reason or "Смотри на их win condition и твои ответы — это ось матчапа.",
            action=action or "Не лезь в лобовую, если у врага готовый ответ и плюс по эликсиру.",
            tip=tip or "Дождись розыгрыша их ключевой защиты — потом дави win condition.",
        )


# Singleton для оркестратора / тестов
_default_generator = TemplateResponseGenerator()

# Alias по ТЗ
TemplateGenerator = TemplateResponseGenerator


def generate_response(ctx: AIContext) -> str:
    """Совместимый entrypoint: всегда Template (поведение не меняется)."""
    from bot.services.ghosteek_ai.generator.factory import get_response_generator

    return get_response_generator("template").generate(ctx)


def compose_answer_from_payload(payload: dict[str, Any]) -> str:
    """Совместимость со старым compose_answer(payload) для тестов."""
    from bot.services.ghosteek_ai.context.ai_context import (
        BattleContext,
        EvaluationContext,
        IntentContext,
        KnowledgeContext,
        RecommendationContext,
    )
    from bot.services.ghosteek_ai.context.builder import ContextBuilder

    intent = str(payload.get("intent") or "")
    ok = bool(payload.get("ok"))
    data = payload.get("data") or {}
    error = payload.get("error")

    if not ok:
        if isinstance(error, str) and error.strip():
            return assert_coach_voice(error)
        ctx = AIContext(
            intent=IntentContext(request=intent, service=""),
            ok=False,
            data=data,
            error_code="CLARIFY",
        )
        return _default_generator.generate(ctx)

    from bot.services.ghosteek_ai.models import Plan, ToolResult

    plan = Plan(intent=intent, service="")
    # Минимальный conversation-less путь: собрать через ToolResult merge
    ctx = AIContext(
        intent=IntentContext(request=intent, service=""),
        ok=True,
        data=data,
        knowledge=KnowledgeContext(),
        recommendation=RecommendationContext(),
    )
    result = ToolResult(tool=intent or "tool", ok=True, data=data)
    ContextBuilder.apply_tool_result(ctx, result)

    if intent == INTENT_CARD_INFO:
        ctx.knowledge.card = dict(data)
    elif intent == INTENT_EXPLAIN_MECHANIC:
        ctx.knowledge.mechanic = dict(data)
    elif intent == INTENT_GAME_COACH:
        ctx.knowledge.coach = dict(data)
    elif intent == INTENT_LAST_BATTLE:
        ctx.battle = BattleContext.from_data(data)
    elif intent == INTENT_MATCHUP:
        ctx.evaluation = EvaluationContext.from_data(data)
    elif intent in {INTENT_ANALYZE_DECK, INTENT_IMPROVE_DECK}:
        rec = data.get("recommendation")
        if isinstance(rec, dict):
            ctx.recommendation.payload = rec
        ctx.recommendation.synergy_score = data.get("synergy_score")
        notes = data.get("synergy_notes")
        if isinstance(notes, list):
            ctx.recommendation.synergy_notes = list(notes)
    elif intent == INTENT_BUILD_DECK:
        core = data.get("core")
        if isinstance(core, list):
            ctx.deck.core = [c for c in core if isinstance(c, str)]
        if isinstance(data.get("decks"), list):
            ctx.deck.built_decks = list(data["decks"])
            ctx.deck.build_mode = data.get("mode")

    return _default_generator.generate(ctx)
