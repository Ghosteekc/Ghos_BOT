"""Local Qwen3 renderer: ToolResult → compact facts → short voice text.

Локальная LLM — не база знаний Clash Royale. Единственный источник фактов —
успешный ToolResult текущего запроса (через compact facts envelope).
"""

from __future__ import annotations

import re
from typing import Any

from bot.services.card_names_ru import CARD_NAMES_RU, CARD_NAMES_SHORT, card_name_ru
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.deck_card import extract_deck_names
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder

INSUFFICIENT_DATA = "По доступным данным я не могу это подтвердить."

# CR mode: живой тренер. Истина только в FACTS/CARDS текущего ToolResult.
LOCAL_RENDERER_SYSTEM_PROMPT = """Ты — Ghosteek AI, дружелюбный игровой тренер по Clash Royale.

Твоя задача — помогать игроку понимать игру, принимать решения и улучшать свою игру.
Ты разговариваешь как живой опытный тренер, а не как API, справочник или командный бот.

## ГЛАВНЫЙ ПРИНЦИП
Ты НЕ являешься источником истины о Clash Royale.
Источник истины — данные текущего Ghosteek AI pipeline в блоках FACTS и CARDS:
данные карт, роли, характеристики, анализ колоды, Deck Builder, RecommendationEngine,
matchup, battle analysis, knowledge/mechanics, coach tips и другие подтверждённые facts из ToolResult.
Используй их как основу ответа. Не подменяй своими воспоминаниями о Clash Royale.

## ФАКТЫ И ВООБРАЖЕНИЕ
Никогда не придумывай игровые факты.
Запрещено самостоятельно выдумывать: названия карт, характеристики, стоимость эликсира,
роли, win conditions, counters, synergies, matchup, механики, события боя,
результаты анализа, состав колоды пользователя, карты вне текущей колоды, числа.
Если нужного факта нет в FACTS/CARDS — не выдумывай его.
Честно скажи, что для точного ответа недостаточно данных.

## КОЛОДА ПОЛЬЗОВАТЕЛЯ
Если Backend передал текущую колоду — именно она источник истины.
Никогда не подменяй её типовой колодой из памяти (Hog 2.6, Log Bait, Giant Beatdown и т.п.).
Перед анализом опирайся на фактический список карт из CARDS/FACTS.
«Разбери мою колоду» = анализируй переданную колоду, не архетип из памяти.
Не добавляй в анализ карты, которых нет в переданной колоде.

## ЗАМЕНА КАРТ
«Что заменить?», «Что поставить вместо X?», «Какая карта тут слабая?» —
сначала данные RecommendationEngine / DeckEvaluator / matchup из FACTS.
Не придумывай замену самостоятельно.
Если в FACTS есть рекомендуемая замена, человеческим языком объясни:
1) какую карту заменить; 2) на что; 3) какую проблему это закрывает; 4) какой компромисс.
Если в FACTS «Замены не нужны» — не предлагай свап.

## СОЗДАНИЕ КОЛОДЫ
Если Backend передал результат Deck Builder — используй именно его.
Не создавай другую колоду самостоятельно.
Можно объяснить идею и роли. Если в FACTS несколько карт в «Ядро» —
озвучь все эти карты как опору сборки (не только первую).
Нельзя подменять результат Builder.

## MATCHUP
Если Backend передал matchup — используй именно его.
Не придумывай counter или matchup из памяти.
Если данных мало — скажи об этом.

## АНАЛИЗ БОЯ
Используй только события и выводы из battle report в FACTS.
Не придумывай, какие карты ставили, когда, сколько эликсира, конкретные ошибки и моменты,
если этого нет в FACTS.
Нет replay frames / event stream — не делай вид, что видел каждое действие.

## ИГРОВЫЕ СОВЕТЫ
Не отвечай шаблоном. Сначала пойми реальную проблему.
Конкретные игровые утверждения — только из доступных данных Ghosteek.

## РАССУЖДЕНИЕ
Перед ответом мысленно: что хочет пользователь; какие факты доступны;
что можно утверждать; что нельзя; как сказать это естественно.
Не показывай внутренний процесс. Только конечный вывод.

## ЖИВОЙ СТИЛЬ
Звучи как нормальный человек, на «ты». Без канцелярита и штампов «Конечно!».
Не начинай каждый ответ одинаково («Твоя колода…», «В нужном направлении…»,
«Сейчас нужно…», «Основная проблема заключается в…»).
Естественные переходы ок («Смотри…», «Тут я бы начал с…», «Похоже, дело не в карте, а в…»),
но не вставляй их механически и не копируй один шаблон подряд.
Лёгкие эмодзи ок, если уместны. Не превращай ответ в набор эмодзи.
Дружелюбный, спокойный, уверенный когда факты есть, честный когда данных мало.
Лёгкий юмор можно. Не токсичный, не свысока, не всезнайка, не осуждай за ошибки.
Не притворяйся человеком.

## ДЛИНА
По умолчанию 2–5 предложений. Список — если задача требует списка.
Подробный разбор — только если просят. Не растягивай простой ответ и не повторяй вопрос.

## НАЗВАНИЯ КАРТ
Имена карт копируй из блока CARDS один в один (русские названия каталога).
Запрещены транслит и выдуманные клички вроде «тумба», «мегавилла», «шаф».
Не латинизируй и не «переводи» имена с английского самостоятельно.

## HARD RULE
Всегда: FACTS → вывод → естественная формулировка.
Никогда: память модели → выдуманный игровой факт → уверенный ответ.
Нет факта в текущих данных Ghosteek — не выдавай его как факт.
Неизвестное имя (блогер, человек, термин) не превращай в карту или стратегию: скажи, что не знаешь.
Нет факта → «По доступным данным я не могу это подтвердить.»
Варьируй формулировки.
"""

# Generation knobs for local renderer (CPU/latency). Ollama top-level think=false.
# Чуть выше temp — живее голос; grounding остаётся на FACTS + validator.
RENDERER_TEMPERATURE = 0.42
RENDERER_TEMPERATURE_CHAT = 0.55
RENDERER_NUM_PREDICT = 220
# Cloud reasoning models (Groq Qwen3) spend tokens on hidden reasoning — need headroom.
RENDERER_NUM_PREDICT_CLOUD = 768
RENDERER_NUM_PREDICT_CLOUD_CHAT = 1024
# CR system prompt + compact FACTS; 2048 вытесняет факты.
RENDERER_NUM_CTX = 4096
RENDERER_NUM_CTX_CHAT = 2048
RENDERER_THINK = False

CONVERSATIONAL_SYSTEM_PROMPT = (
    "Ты Ghosteek — AI-коуч Clash Royale в этом приложении. "
    "Отвечай живо, на «ты», 1–3 короткими предложениями. "
    "Дружелюбно и спокойно, без канцелярита и штампов «Конечно!». "
    "Не представляйся каждый раз. Не притворяйся человеком. "
    "Без грубости, политики и 18+. Не советуй конкретные карты, числа и мету. "
    "Не выдумывай факты: карты, механики, стратегии, блогеров, людей. "
    "Если не знаешь — так и скажи, коротко и честно. "
    "Не превращай неизвестное имя в карту или тактику. "
    "Варьируй формулировки — не копируй один шаблон."
)

CONVERSATIONAL_UNKNOWN_TOPIC_NOTE = (
    "Этого нет в данных Ghosteek. Скажи, что не знаешь. "
    "Не выдумывай карту, стратегию или биографию."
)

# Envelope tools: conversational / soft-clarify — не CR ToolResult.
CAPABILITY_CLARIFY_TOOL = "capability"
CONVERSATIONAL_TOOL = "chat"

_CAPABILITY_CLARIFY_FACTS: tuple[str, ...] = (
    "Роль: Ghosteek — живой AI-коуч Clash Royale в этом приложении (не человек).",
    "Можешь помочь с: сборкой колоды, разбором состава, матчапом или боем, "
    "объяснением карты или термина.",
    "Правило: без конкретной игровой задачи не советуй карты, замены и мету из памяти.",
    "Тон: короткий, естественный; можно лёгкую шутку или эмодзи.",
)

_VOICE_VARIATION_PATTERNS: tuple[str, ...] = (
    "Форма: прямой совет, без воды.",
    "Форма: дружеский короткий комментарий.",
    "Форма: краткий разбор по пунктам из FACTS.",
    "Форма: уверенная рекомендация на «ты».",
    "Форма: осторожная рекомендация («я бы…»).",
    "Форма: разговорное объяснение одним куском.",
)

_SOFT_CLARIFY_RE = re.compile(
    r"^\s*(?:"
    r"привет\w*|здравствуй(?:те)?|хай|hello|hi|hey|йо|здарова|"
    r"салам(?:\s+алейкум)?|ассаламу\s+алейкум|assalamu\s+alaikum|"
    r"добр(?:ое|ый|ой)\s+(?:утро|день|вечер)|"
    r"как\s+дела(?:\s+\w+)?|что\s+(?:ты\s+)?умеешь|кто\s+ты|помощь|help|"
    r"что\s+можешь|чем\s+поможешь|спасибо|расскажи\s+про\s+себя|"
    r"а\s+ты\s+вообще\s+кто|мне\s+скучно"
    r")[\s!.?…]*$",
    re.IGNORECASE,
)

_MAX_FACTS_FOR_LLM = 8
_MAX_CARDS_FOR_LLM = 12
_MAX_USER_CHARS = 160
_MAX_PREV_ANSWER_CHARS = 180
_MAX_FACTS_LINE_CHARS = 120

_FOLLOWUP_WHY = ("а почему", "почему так", "почему?", "почему ")
_FOLLOWUP_DETAIL = ("подробнее", "детальнее", "разверни", "ещё раз", "еще раз")
_FOLLOWUP_MATCHUP = ("против ", "а против", "vs ", "матчап")

_CARD_KEYS = frozenset(
    {
        "deck",
        "cards",
        "user_deck",
        "opponent_deck",
        "opponent_cards",
        "improved_deck",
        "original_deck",
        "core",
        "locked",
        "suggested_cards",
    }
)
# Не тащить в allowlist кандидатов/дыры из evaluator — иначе LLM легально пишет Inferno Tower.
_WALK_SKIP_KEYS = frozenset(
    {
        "evaluation_report",
        "candidate_ranking",
        "sanity_report",
        "rejected",
        "why_gaps",
        "open_gaps",
        "balance_issues",
        "rejected_candidates",
    }
)

def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
    return out


def _add_card(bucket: list[str], seen: set[str], name: Any) -> None:
    if not isinstance(name, str):
        return
    text = name.strip()
    if not text:
        return
    key = text.lower()
    if key in seen:
        return
    seen.add(key)
    bucket.append(text)


def _walk_cards(raw: Any, bucket: list[str], seen: set[str], *, key_hint: str | None = None) -> None:
    if isinstance(raw, list):
        if key_hint in _CARD_KEYS or key_hint in {"drop", "pick", "primary_win", "name"}:
            for item in raw:
                if isinstance(item, str):
                    _add_card(bucket, seen, item)
                elif isinstance(item, dict):
                    _add_card(bucket, seen, item.get("name"))
                    _walk_cards(item, bucket, seen, key_hint=None)
        else:
            for item in raw:
                _walk_cards(item, bucket, seen, key_hint=key_hint)
        return
    if not isinstance(raw, dict):
        return
    for key, val in raw.items():
        key_l = str(key).lower()
        if key_l in _WALK_SKIP_KEYS:
            continue
        if key_l in _CARD_KEYS or key_l in {"drop", "pick", "primary_win"}:
            if isinstance(val, str):
                _add_card(bucket, seen, val)
            elif isinstance(val, list):
                _walk_cards(val, bucket, seen, key_hint=key_l)
            elif isinstance(val, dict) and key_l == "deck_card":
                for n in extract_deck_names(val):
                    _add_card(bucket, seen, n)
        elif key_l == "name" and isinstance(val, str) and val.strip() in CARD_NAMES_RU:
            _add_card(bucket, seen, val)
        elif key_l == "decks" and isinstance(val, list):
            for entry in val:
                if isinstance(entry, dict):
                    for n in extract_deck_names(entry):
                        _add_card(bucket, seen, n)
        elif isinstance(val, (dict, list)):
            _walk_cards(val, bucket, seen, key_hint=key_l)


def collect_allowed_card_ids(data: dict[str, Any], ctx: AIContext | None = None) -> list[str]:
    cards: list[str] = []
    seen: set[str] = set()
    _walk_cards(data, cards, seen)
    if ctx is not None:
        for n in list(ctx.deck.cards) + list(ctx.deck.opponent_cards) + list(ctx.deck.core):
            _add_card(cards, seen, n)
        if isinstance(ctx.deck_card, dict):
            for n in extract_deck_names(ctx.deck_card):
                _add_card(cards, seen, n)
        cq = getattr(ctx.intent, "card_query", None)
        if cq:
            _add_card(cards, seen, cq)
    return cards


def _first_str(*values: Any) -> str:
    for val in values:
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return ""


def _push_fact(facts: list[str], line: str) -> None:
    text = (line or "").strip()
    if not text or text in facts:
        return
    facts.append(text)


def _avg_elixir_from_data(data: dict[str, Any], ctx: AIContext | None) -> float | None:
    for key in ("avg_elixir", "average_elixir"):
        val = data.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    deck_card = data.get("deck_card")
    if isinstance(deck_card, dict):
        for key in ("avg_elixir", "average_elixir"):
            val = deck_card.get(key)
            if isinstance(val, (int, float)):
                return float(val)
    if ctx is not None and isinstance(ctx.deck_card, dict):
        for key in ("avg_elixir", "average_elixir"):
            val = ctx.deck_card.get(key)
            if isinstance(val, (int, float)):
                return float(val)
    return None


def _facts_deck_analysis(
    data: dict[str, Any],
    ctx: AIContext | None,
    *,
    tool: str = "deck_analysis",
) -> list[str]:
    facts: list[str] = []
    rec = data.get("recommendation") if isinstance(data.get("recommendation"), dict) else {}
    intent = rec.get("intent") if isinstance(rec.get("intent"), dict) else {}
    coaching = rec.get("coaching") if isinstance(rec.get("coaching"), dict) else {}
    gp = rec.get("game_plan") if isinstance(rec.get("game_plan"), dict) else {}
    plan = rec.get("improvement_plan") if isinstance(rec.get("improvement_plan"), dict) else {}
    balance = rec.get("balance_issues") if isinstance(rec.get("balance_issues"), dict) else {}

    primary = intent.get("primary_win")
    if isinstance(primary, str) and primary.strip():
        _push_fact(facts, f"Основная win condition: {primary.strip()}")

    avg = _avg_elixir_from_data(data, ctx)
    if avg is not None:
        _push_fact(facts, f"Средняя стоимость: {avg}")

    style = coaching.get("play_style")
    if isinstance(style, str) and style.strip():
        _push_fact(facts, f"Стиль: {style.strip()}")

    strength = _first_str(coaching.get("strengths"), data.get("synergy_notes"))
    if strength:
        _push_fact(facts, f"Сильная сторона: {strength}")

    weakness = _first_str(gp.get("critical_weaknesses"), balance.get("messages"))
    if weakness and tool != "recommendation":
        _push_fact(facts, f"Основная проблема: {weakness}")

    how = gp.get("how_to_win")
    if isinstance(how, str) and how.strip() and tool != "recommendation":
        _push_fact(facts, f"Как побеждать: {how.strip()}")

    # Не светим «min_air_defense» как дыру — модель начинает выдумывать свапы «против воздуха».
    score = data.get("synergy_score")
    if isinstance(score, (int, float)):
        _push_fact(facts, f"Оценка колоды (synergy): {score}")

    if plan.get("needed"):
        step = plan.get("steps")
        if isinstance(step, list) and step:
            first = step[0] if isinstance(step[0], dict) else {}
            msg = first.get("message") or first.get("reason")
            drop = first.get("drop")
            pick = first.get("pick")
            if isinstance(drop, str) and isinstance(pick, str) and drop.strip() and pick.strip():
                _push_fact(facts, f"Рекомендуемая замена: {drop.strip()} → {pick.strip()}")
            if isinstance(msg, str) and msg.strip():
                _push_fact(facts, f"Причина замены: {msg.strip()}")
    elif tool == "recommendation":
        _push_fact(
            facts,
            "Замены не нужны. Не предлагай свап карт и не выдумывай причины замены.",
        )
    return facts


def _facts_matchup(data: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    if data.get("rating") is not None:
        _push_fact(facts, f"Оценка матчапа: {data.get('rating')}")
    score = data.get("score")
    if isinstance(score, (int, float)):
        _push_fact(facts, f"Счёт матчапа: {score}")
    for key, label in (
        ("reasons", "Причина"),
        ("advantages", "Преимущество"),
        ("disadvantages", "Риск"),
    ):
        for item in _as_str_list(data.get(key))[:3]:
            _push_fact(facts, f"{label}: {item}")
    return facts


def _facts_battle(data: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    if data.get("won") is True:
        _push_fact(facts, "Исход боя: победа")
    elif data.get("won") is False:
        _push_fact(facts, "Исход боя: поражение")
    if data.get("opponent_name"):
        _push_fact(facts, f"Соперник: {data.get('opponent_name')}")
    if data.get("matchup_score") is not None:
        _push_fact(facts, f"Оценка матчапа: {data.get('matchup_score')}")
    summary = data.get("outcome_summary")
    if isinstance(summary, str) and summary.strip():
        _push_fact(facts, f"Итог: {summary.strip()}")
    for reason in _as_str_list(data.get("reasons"))[:4]:
        _push_fact(facts, f"Причина: {reason}")
    md = data.get("match_difficulty")
    if isinstance(md, dict):
        if md.get("difficulty") is not None:
            _push_fact(facts, f"Сложность: {md.get('difficulty')}")
        for reason in _as_str_list(md.get("reasons"))[:2]:
            _push_fact(facts, f"Сложность — причина: {reason}")
    mp = data.get("match_plan")
    if isinstance(mp, dict):
        if mp.get("win_condition_window"):
            _push_fact(facts, f"Окно вин-кондишна: {mp.get('win_condition_window')}")
        for item in _as_str_list(mp.get("avoid"))[:3]:
            _push_fact(facts, f"Избегать: {item}")
        for item in _as_str_list(mp.get("phase_1"))[:2]:
            _push_fact(facts, f"Фаза 1: {item}")
    return facts


def _facts_card_info(data: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    if data.get("name"):
        _push_fact(facts, f"Карта: {data.get('name')}")
    if data.get("name_ru"):
        _push_fact(facts, f"Русское название: {data.get('name_ru')}")
    if data.get("elixir") is not None:
        _push_fact(facts, f"Стоимость эликсира: {data.get('elixir')}")
    if data.get("card_type"):
        _push_fact(facts, f"Тип: {data.get('card_type')}")
    roles = data.get("roles")
    if isinstance(roles, list) and roles:
        _push_fact(facts, "Роли: " + ", ".join(str(r) for r in roles if r))
    return facts


def _facts_knowledge(data: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    for key, label in (
        ("title", "Тема"),
        ("summary", "Суть"),
        ("example", "Пример"),
        ("tip", "Совет"),
        ("answer", "Ответ"),
    ):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            _push_fact(facts, f"{label}: {val.strip()}")
    return facts


def _facts_coach(data: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    if data.get("topic"):
        _push_fact(facts, f"Тема коуча: {data.get('topic')}")
    for tip in _as_str_list(data.get("tips"))[:4]:
        _push_fact(facts, f"Совет: {tip}")
    facts.extend(_facts_matchup(data))
    return facts


def _facts_deck_builder(data: dict[str, Any], ctx: AIContext | None) -> list[str]:
    facts: list[str] = []
    mode = data.get("mode") or data.get("stage")
    if mode:
        _push_fact(facts, f"Режим сборки: {mode}")
    avg = _avg_elixir_from_data(data, ctx)
    if avg is not None:
        _push_fact(facts, f"Средняя стоимость: {avg}")
    decks = data.get("decks")
    shown = False
    if isinstance(decks, list) and decks:
        first = decks[0] if isinstance(decks[0], dict) else {}
        arch = first.get("archetype") or first.get("category") or first.get("name")
        if arch:
            _push_fact(facts, f"Архетип сборки: {arch}")
        shown = True
    elif isinstance(data.get("deck_card"), dict) or (ctx and ctx.deck_card):
        card = (
            data.get("deck_card")
            if isinstance(data.get("deck_card"), dict)
            else (ctx.deck_card if ctx else {})
        )
        arch = (card or {}).get("archetype")
        if arch:
            _push_fact(facts, f"Архетип сборки: {arch}")
        shown = True
    if shown:
        _push_fact(facts, "Колода показана в UI — не перечисляй карты в тексте.")
        _push_fact(
            facts,
            "Сборка полная. Представь её как готовый вариант, не проси доделывать.",
        )
    core = _as_str_list(data.get("core"))
    if core:
        core_ru = [card_name_ru(c, short=True) for c in core[:4]]
        _push_fact(facts, "Ядро (озвучь все): " + ", ".join(core_ru))
    return facts


def extract_facts_lines(tool: str, data: dict[str, Any], ctx: AIContext | None = None) -> list[str]:
    tool_l = (tool or "").strip().lower()
    if tool_l in {"deck_analysis", "recommendation"}:
        return _facts_deck_analysis(data, ctx, tool=tool_l)
    if tool_l == "deck_builder":
        return _facts_deck_builder(data, ctx)
    if tool_l == "matchup":
        return _facts_matchup(data)
    if tool_l == "battle_analysis":
        return _facts_battle(data)
    if tool_l == "card_info":
        return _facts_card_info(data)
    if tool_l in {"knowledge", "mechanics"}:
        return _facts_knowledge(data)
    if tool_l == "game_coach":
        return _facts_coach(data)

    facts: list[str] = []
    for key, val in data.items():
        if key in {
            "deck",
            "cards",
            "user_deck",
            "opponent_deck",
            "decks",
            "recommendation",
            "evaluation_report",
        }:
            continue
        if isinstance(val, (str, int, float)) and str(val).strip():
            _push_fact(facts, f"{key}: {val}")
        elif isinstance(val, list) and val and all(isinstance(x, str) for x in val[:3]):
            _push_fact(facts, f"{key}: " + ", ".join(val[:3]))
    return facts[:12]


def _answer_constraints(tool: str, intent: str | None) -> list[str]:
    intent_l = (intent or "").strip().lower()
    tool_l = (tool or "").strip().lower()
    constraints = [
        "Используй только facts / allowed_card_ids / allowed_entities.",
        f"Если данных нет: «{INSUFFICIENT_DATA}»",
        "Не добавляй generic coach tips.",
        "Не выдумывай карты, числа и механики.",
        "Тон: живой и естественный, не сухой бот и не анкета.",
        "Не копируй один шаблон — варьируй формулировки при той же сути.",
    ]
    if tool_l in {CAPABILITY_CLARIFY_TOOL, CONVERSATIONAL_TOOL} or intent_l == "chat":
        constraints.append(
            "Разговорный ответ: 1–3 предложения. Без карт, меты и чисел."
        )
    elif tool_l == "recommendation" or intent_l == "improve_deck":
        constraints.append(
            "Если в FACTS «Замены не нужны» — скажи, что состав рабочий, без свапов. "
            "Если есть «Рекомендуемая замена» — озвучь только её и причину из FACTS. "
            "Не приписывай картам воздух/DPS/синергию, которых нет в FACTS."
        )
    elif tool_l == "deck_analysis" or intent_l == "analyze_deck":
        constraints.append(
            "Сначала ясный вывод, потом 1–2 причины из FACTS. "
            "Не предлагай замену карт, если в FACTS нет «Рекомендуемая замена»."
        )
    elif tool_l == "matchup" or intent_l == "matchup":
        constraints.append("Что делать → почему → ключевая ошибка (только из FACTS).")
    elif tool_l == "deck_builder" or intent_l == "build_deck":
        constraints.append(
            "Не перечисляй карты текстом — UI показывает колоду. "
            "2–3 живых предложения с глаголами: что собрал и как этим играть. "
            "Если в FACTS «Ядро» из нескольких карт — назови все эти карты как опору, не одну. "
            "Не ругай сборку и не проси игрока её доделывать — колода уже полная."
        )
    elif tool_l == "game_coach" or intent_l == "game_coach":
        constraints.append("Один конкретный совет + краткое объяснение из FACTS.")
    else:
        constraints.append("Обычный ответ: 2–5 предложений.")
    return constraints


def _pick_voice_variation(seed: str) -> str:
    key = (seed or "ghosteek").encode("utf-8", errors="ignore")
    idx = abs(hash(key)) % len(_VOICE_VARIATION_PATTERNS)
    return _VOICE_VARIATION_PATTERNS[idx]


def is_soft_clarify_message(message: str) -> bool:
    """Привет / «что умеешь» — можно озвучить capability-facts через LLM."""
    text = (message or "").strip()
    if not text or len(text) > 80:
        return False
    return bool(_SOFT_CLARIFY_RE.match(text))


def classify_chat_kind(message: str) -> str:
    """Подтип small talk (подсказка стиля, не шаблон ответа)."""
    low = (message or "").strip().lower().replace("ё", "е")
    if any(k in low for k in ("спасибо", "благодар", "спс")):
        return "thanks"
    if any(k in low for k in ("как дела", "как ты", "как сам", "что делаешь")):
        return "how_are_you"
    if any(
        k in low
        for k in (
            "кто ты",
            "про себя",
            "о себе",
            "разбираешь",
            "что умеешь",
            "что можешь",
            "тренер",
        )
    ):
        return "about"
    if any(k in low for k in ("скучно", "посоветуй", "поделать", "заняться")):
        return "idle"
    if any(k in low for k in ("ахах", "лол", "кек", "понятно", "ясно", "ок", "окей", "красав")):
        return "ack"
    return "greeting"


_UNKNOWN_TOPIC_HINTS = (
    "блогер",
    "блогеров",
    "ютубер",
    "стример",
    "видеоблог",
    "тиктокер",
    "youtube",
    "ютуб",
)
_UNKNOWN_TOPIC_ASK = (
    "расскажи про",
    "расскажи о",
    "кто такой",
    "кто такая",
    "что за ",
    "какие популярн",
)


def conversational_unknown_topic_note(message: str) -> str:
    """Если вопрос не про карту/механику из данных — напомнить модели не выдумывать."""
    low = (message or "").strip().lower().replace("ё", "е")
    if not low:
        return ""
    if "про себя" in low or "о себе" in low:
        return ""
    if any(h in low for h in _UNKNOWN_TOPIC_HINTS):
        return CONVERSATIONAL_UNKNOWN_TOPIC_NOTE
    if any(h in low for h in _UNKNOWN_TOPIC_ASK):
        try:
            from bot.services.ghosteek_ai.intents import extract_cards_from_text

            if extract_cards_from_text(message):
                return ""
        except Exception:
            pass
        return CONVERSATIONAL_UNKNOWN_TOPIC_NOTE
    return ""


def build_capability_clarify_envelope() -> dict[str, Any]:
    """FACTS-only envelope для soft-clarify: без карт и без ToolResult домена."""
    facts = list(_CAPABILITY_CLARIFY_FACTS)
    return {
        "tool": CAPABILITY_CLARIFY_TOOL,
        "ok": True,
        "data": {
            "facts": facts,
            "allowed_card_ids": [],
            "allowed_entities": _allowed_entities(facts, []),
            "answer_constraints": _answer_constraints(CAPABILITY_CLARIFY_TOOL, "clarify"),
        },
    }


def build_conversational_envelope(message: str = "") -> dict[str, Any]:
    """MODE A: нет игрового ToolResult. Envelope только для style/safety gate."""
    kind = classify_chat_kind(message)
    facts = [
        "Режим: свободный разговор, не игровой анализ.",
        "Не называй конкретные карты и не давай мету/числа.",
        "Не выдумывай факты. Если не знаешь — скажи, что не знаешь.",
    ]
    unknown = conversational_unknown_topic_note(message)
    if unknown:
        facts.append(unknown)
    return {
        "tool": CONVERSATIONAL_TOOL,
        "ok": True,
        "data": {
            "facts": facts,
            "allowed_card_ids": [],
            "allowed_entities": _allowed_entities(facts, []),
            "answer_constraints": _answer_constraints(CONVERSATIONAL_TOOL, "chat"),
            "chat_kind": kind,
        },
    }


def attach_capability_clarify_facts(ctx: AIContext) -> dict[str, Any]:
    envelope = build_capability_clarify_envelope()
    ctx.render_facts = envelope
    # Soft-clarify is a valid coach turn — not a failed tool (ok=False → template clarify).
    ctx.ok = True
    ctx.error_code = None
    ctx.error_params = {}
    return envelope


def attach_conversational_facts(ctx: AIContext) -> dict[str, Any]:
    envelope = build_conversational_envelope(ctx.raw_message or "")
    ctx.render_facts = envelope
    # Chat has no ToolResult; default ok=False would make Template emit CLARIFY.
    ctx.ok = True
    ctx.error_code = None
    ctx.error_params = {}
    return envelope


def can_render_capability_clarify(ctx: AIContext) -> bool:
    return is_soft_clarify_message(ctx.raw_message or "")


def can_render_conversational(ctx: AIContext) -> bool:
    intent = str(getattr(getattr(ctx, "intent", None), "request", None) or "").lower()
    if intent == "chat":
        return True
    return is_soft_clarify_message(ctx.raw_message or "")


def _allowed_entities(facts: list[str], cards: list[str]) -> list[str]:
    entities: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        text = item.strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        entities.append(text)

    for card in cards:
        add(card)
        add(card_name_ru(card))
        short = CARD_NAMES_SHORT.get(card)
        if short:
            add(short)
    for line in facts:
        add(line)
        if ":" in line:
            add(line.split(":", 1)[1].strip())
    add(INSUFFICIENT_DATA)
    return entities


def _primary_tool_payload(ctx: AIContext) -> tuple[str, dict[str, Any]]:
    outputs = ctx.tool_outputs or {}
    for name, raw in outputs.items():
        if not isinstance(raw, dict):
            continue
        if raw.get("ok") is False:
            continue
        tool = str(raw.get("tool") or name)
        if tool in {"clarify", "unsupported"}:
            continue
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        return tool, dict(data)
    if ctx.ok and isinstance(ctx.data, dict) and ctx.data:
        tool = (ctx.service or ctx.intent.request or "tool").strip() or "tool"
        return tool, dict(ctx.data)
    return "", {}


def build_facts_envelope(ctx: AIContext) -> dict[str, Any]:
    """LLM-facing compact envelope. Не заменяет ToolResult / API contract."""
    tool, data = _primary_tool_payload(ctx)
    cards = collect_allowed_card_ids(data, ctx)
    facts = extract_facts_lines(tool, data, ctx)
    intent = getattr(ctx.intent, "request", None)
    constraints = _answer_constraints(tool, intent)
    # Controlled variation: меняет только форму, не факты.
    seed = f"{tool}:{intent}:{(ctx.raw_message or '').strip().lower()}"
    constraints.append(_pick_voice_variation(seed))
    return {
        "tool": tool or "unknown",
        "ok": True,
        "data": {
            "facts": facts,
            "allowed_card_ids": cards,
            "allowed_entities": _allowed_entities(facts, cards),
            "answer_constraints": constraints,
        },
    }


def attach_render_facts(ctx: AIContext) -> dict[str, Any]:
    envelope = build_facts_envelope(ctx)
    # Follow-up: reuse previous compact facts when current tool gave nothing useful.
    kind = detect_followup_kind(ctx.raw_message or "")
    prev = _prev_render_facts(ctx)
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    facts = list(data.get("facts") or []) if isinstance(data, dict) else []
    cards = list(data.get("allowed_card_ids") or []) if isinstance(data, dict) else []
    thin = not facts and not cards
    if kind and prev and thin:
        # Reuse previous facts only when the current tool returned nothing usable.
        envelope = dict(prev)
        envelope["ok"] = True
    ctx.render_facts = envelope
    if kind:
        ctx.request_context = dict(ctx.request_context or {})
        ctx.request_context["_renderer_followup"] = kind
    return envelope


def detect_followup_kind(message: str) -> str | None:
    low = (message or "").lower().strip()
    if not low:
        return None
    if any(k in low for k in _FOLLOWUP_WHY):
        return "why"
    if any(k in low for k in _FOLLOWUP_DETAIL):
        return "detail"
    if any(k in low for k in _FOLLOWUP_MATCHUP):
        return "matchup"
    return None


def _prev_render_facts(ctx: AIContext) -> dict[str, Any] | None:
    req = ctx.request_context if isinstance(ctx.request_context, dict) else {}
    raw = req.get("last_render_facts")
    if isinstance(raw, dict) and raw.get("data"):
        return dict(raw)
    return None


def _prev_answer_brief(ctx: AIContext) -> str:
    req = ctx.request_context if isinstance(ctx.request_context, dict) else {}
    brief = str(req.get("last_answer_brief") or "").strip()
    if brief:
        return brief[:_MAX_PREV_ANSWER_CHARS]
    # Fallback: last assistant turn in conversation slice (already short).
    for turn in reversed(ctx.recent_messages or []):
        if not isinstance(turn, dict):
            continue
        if str(turn.get("role") or "").lower() in {"assistant", "ai", "bot", "coach"}:
            content = str(turn.get("content") or "").strip()
            if content:
                return content[:_MAX_PREV_ANSWER_CHARS]
    return ""


def _card_label_for_llm(en: str) -> str:
    ru = card_name_ru(en)
    return ru or en


def _ruify_card_names(text: str) -> str:
    """EN-имена из каталога → русские подписи, длинные первыми."""
    raw = text or ""
    if not raw:
        return raw
    out = raw
    for en, ru in sorted(CARD_NAMES_RU.items(), key=lambda x: len(x[0]), reverse=True):
        if not en or not ru or en.lower() == ru.lower():
            continue
        out = re.sub(rf"(?<!\w){re.escape(en)}(?!\w)", ru, out, flags=re.IGNORECASE)
    return out


def compact_facts_for_llm(envelope: dict[str, Any]) -> str:
    """Минимальный FACTS-блок для LLM (не полный ToolResult / не validator JSON)."""
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    tool = str(envelope.get("tool") or "").strip()
    facts = [
        _ruify_card_names(str(x).strip()[:_MAX_FACTS_LINE_CHARS])
        for x in (data.get("facts") or [])
        if str(x).strip()
    ][:_MAX_FACTS_FOR_LLM]
    cards = [
        _card_label_for_llm(str(x).strip())
        for x in (data.get("allowed_card_ids") or [])
        if isinstance(x, str) and x.strip()
    ][:_MAX_CARDS_FOR_LLM]

    lines: list[str] = []
    if tool:
        lines.append(f"tool={tool}")
    if facts:
        lines.append("FACTS:")
        lines.extend(f"- {f}" for f in facts)
    if cards:
        lines.append("CARDS: " + ", ".join(cards))
    constraints = [
        str(x).strip()[:_MAX_FACTS_LINE_CHARS]
        for x in (data.get("answer_constraints") or [])
        if str(x).strip()
    ]
    # В LLM — только специфичные STYLE (последние), без повтора generic lock.
    style = [
        c
        for c in constraints
        if c.lower().startswith(
            (
                "формат",
                "форма:",
                "сначала",
                "что делать",
                "не перечисл",
                "один конкрет",
                "обычный",
                "поприветствуй",
                "разговорный",
                "тон:",
                "если в facts",
                "если есть",
                "не предлагай",
                "не приписывай",
                "контекст:",
            )
        )
        or c.lower().startswith("форма:")
    ]
    if not style and constraints:
        style = constraints[-2:] if len(constraints) >= 2 else constraints[-1:]
    if style:
        lines.append("STYLE:")
        lines.extend(f"- {c}" for c in style[-3:])
    if not facts and not cards:
        lines.append("FACTS: (empty)")
    return "\n".join(lines)


def short_user_request(ctx: AIContext) -> str:
    text = (ctx.raw_message or "").strip()
    if not text:
        return "(пусто)"
    if len(text) > _MAX_USER_CHARS:
        return text[: _MAX_USER_CHARS - 1] + "…"
    return text


def estimate_prompt_chars(messages: list[ChatMessage]) -> int:
    return sum(len(m.content or "") for m in messages)


def can_reuse_last_facts_for_followup(ctx: AIContext) -> bool:
    """True если CR follow-up и есть сохранённые facts — не для small talk."""
    raw = ctx.raw_message or ""
    try:
        from bot.services.ghosteek_ai.intents import _is_chat_request

        if _is_chat_request(raw.lower().replace("ё", "е")):
            return False
    except Exception:
        pass
    intent = str(getattr(getattr(ctx, "intent", None), "request", None) or "").lower()
    if intent == "chat":
        kind = detect_followup_kind(raw)
        if kind not in {"why", "detail"}:
            return False
    else:
        kind = detect_followup_kind(raw)
        if not kind:
            return False
    prev = _prev_render_facts(ctx)
    if not prev:
        return False
    tool = str(prev.get("tool") or "").strip().lower()
    if tool in {CONVERSATIONAL_TOOL, CAPABILITY_CLARIFY_TOOL, "clarify", "unsupported"}:
        return False
    data = prev.get("data") if isinstance(prev.get("data"), dict) else {}
    facts = data.get("facts") or []
    cards = data.get("allowed_card_ids") or []
    return bool(facts or cards)


def renderer_generate_kwargs(
    *,
    conversational: bool = False,
    backend: str = "",
) -> dict[str, Any]:
    """Параметры генерации для LocalRenderer (Ollama и cloud Qwen/Groq).

    think всегда False на этом пути — не генерировать reasoning (не просто скрывать).
    """
    from bot.config import settings

    temp = RENDERER_TEMPERATURE_CHAT if conversational else RENDERER_TEMPERATURE
    key = (backend or "").strip().lower()
    cloud = key in {
        "qwen",
        "dashscope",
        "openai",
        "openai_compatible",
        "groq",
    }

    if cloud:
        # Groq/Qwen thinking models burn max_tokens on reasoning → content cuts mid-word.
        floor = (
            RENDERER_NUM_PREDICT_CLOUD_CHAT
            if conversational
            else RENDERER_NUM_PREDICT_CLOUD
        )
        max_tokens = int(getattr(settings, "llm_max_tokens", 0) or 0) or floor
        max_tokens = max(max_tokens, floor)
        return {
            "temperature": float(temp),
            "max_tokens": max_tokens,
            "think": False,
        }

    configured = int(getattr(settings, "ollama_num_ctx", 0) or 0)
    if conversational:
        num_ctx = configured or RENDERER_NUM_CTX_CHAT
    else:
        floor = RENDERER_NUM_CTX
        num_ctx = max(configured, floor) if configured else floor
    return {
        "temperature": float(
            getattr(settings, "ollama_temperature", temp) or temp
        ),
        "max_tokens": int(
            getattr(settings, "ollama_num_predict", RENDERER_NUM_PREDICT)
            or RENDERER_NUM_PREDICT
        ),
        "num_ctx": num_ctx,
        "think": False,
    }


def find_ungrounded_card_mentions(text: str, allowed_card_ids: list[str]) -> list[str]:
    """Canonical EN ids mentioned in text but not in allowlist."""
    from bot.services.ghosteek_ai.safety.local_renderer_validator import (
        find_ungrounded_cards,
    )

    return find_ungrounded_cards(text, allowed_card_ids)


def ground_local_renderer_text(text: str, envelope: dict[str, Any] | None) -> str:
    """Совместимость: делегирует в строгий gate (без эвристического ремонта)."""
    from bot.services.ghosteek_ai.safety.local_renderer_validator import (
        apply_local_renderer_gate,
    )

    return apply_local_renderer_gate(text, envelope)


class LocalRendererPromptBuilder(PromptBuilder):
    """CR trainer system + compact FACTS + user. Chat — отдельный conversational prompt."""

    def __init__(self) -> None:
        super().__init__(system_prompt=LOCAL_RENDERER_SYSTEM_PROMPT, constraints="")

    def build(
        self,
        ctx: AIContext,
        *,
        include_tool_results: bool = True,
        planner_recommendation: Any | None = None,
    ) -> list[ChatMessage]:
        del include_tool_results, planner_recommendation
        envelope = getattr(ctx, "render_facts", None)
        if not isinstance(envelope, dict) or not envelope:
            envelope = attach_render_facts(ctx)

        tool = str(envelope.get("tool") or "").strip().lower()
        if tool == CONVERSATIONAL_TOOL:
            messages = [
                ChatMessage(role=MessageRole.SYSTEM, content=CONVERSATIONAL_SYSTEM_PROMPT),
            ]
            unknown = conversational_unknown_topic_note(ctx.raw_message or "")
            if unknown:
                messages.append(ChatMessage(role=MessageRole.SYSTEM, content=unknown))
            messages.append(
                ChatMessage(role=MessageRole.USER, content=short_user_request(ctx))
            )
            return messages

        kind = (ctx.request_context or {}).get("_renderer_followup") or detect_followup_kind(
            ctx.raw_message or ""
        )
        facts_block = compact_facts_for_llm(envelope)
        # Capability/small-talk facts ≠ CR pipeline: не подключаем CR trainer prompt.
        system = (
            CONVERSATIONAL_SYSTEM_PROMPT
            if tool == CAPABILITY_CLARIFY_TOOL
            else LOCAL_RENDERER_SYSTEM_PROMPT
        )

        messages: list[ChatMessage] = [
            ChatMessage(role=MessageRole.SYSTEM, content=system),
            ChatMessage(role=MessageRole.SYSTEM, content=facts_block),
        ]

        # Follow-up hints — только необходимый контекст, не вся история.
        if kind == "why":
            prev = _prev_answer_brief(ctx)
            if prev:
                messages.append(
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=f"PREV_ANSWER: {prev}",
                    )
                )
                messages.append(
                    ChatMessage(
                        role=MessageRole.SYSTEM,
                        content=(
                            "Задача: коротко и по-человечески объясни PREV_ANSWER "
                            "только по FACTS."
                        ),
                    )
                )
        elif kind == "detail":
            messages.append(
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content="Задача: чуть подробнее по FACTS, без новых сущностей.",
                )
            )
        elif kind == "matchup":
            messages.append(
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content="Задача: ответ по матчапу из FACTS (что делать → почему).",
                )
            )

        tool = str(envelope.get("tool") or "").strip().lower()
        if tool == CAPABILITY_CLARIFY_TOOL:
            messages.append(
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Задача: тепло ответь на вопрос о возможностях только по FACTS. "
                        "Без карт и меты. Варьируй формулировки."
                    ),
                )
            )

        messages.append(
            ChatMessage(role=MessageRole.USER, content=short_user_request(ctx))
        )
        return messages

    def build_user_message(self, ctx: AIContext) -> list[ChatMessage]:
        return [ChatMessage(role=MessageRole.USER, content=short_user_request(ctx))]
