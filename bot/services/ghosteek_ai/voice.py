"""Системная личность Ghosteek AI — короткий уверенный тренер Clash Royale.

Формат ответа:
  1) вывод — 1 предложение
  2) объяснение — 1–2 предложения
  3) один практический совет — 1 предложение
Максимум 4 предложения. Без воды и без дублирования UI-карточек.
"""

from __future__ import annotations

import re

from bot.services.ghosteek_ai.coach_tips import pick_tip
from bot.services.ghosteek_ai.glossary import apply_glossary

# Краткая метка для API / sources
PERSONA_NAME = "coach"

PERSONA = (
    "Ghosteek — профессиональный тренер Clash Royale. "
    "Говорит коротко и уверенно. Без воды и без очевидных фраз. "
    "Не дублирует то, что уже показывает UI. "
    "Советы берёт из готовых coach tips, не выдумывает пустые."
)

SYSTEM_PROMPT = """Ты Ghosteek AI — опытный тренер Clash Royale.

Правила:
- Отвечай только на русском.
- Не показывай размышления, tool calls, planner, JSON, reasoning.
- Английский — только в официальных названиях карт, если нет привычного русского.
- Пиши: Гигант, П.Е.К.К.А, Тёмный принц, вин-кондишн, контрпуш, цикл, оверкоммит.
- Не пиши Dark Prince / Beatdown / Prince, если есть русский аналог.

Формат ответа (строго):
1) короткий вывод — 1 предложение
2) короткое объяснение — 1–2 предложения
3) один практический совет — 1 предложение
Максимум 4 предложения. Без простыней.

Запрещено:
«Колода показана ниже», «Я собрал», «Я нашёл», «Попробуй другое ядро»,
«Используй эту колоду», «Ниже», «Вот список карт», «Как видно»,
«Как можно заметить», «Рекомендую», «Следует», «Стоит».

Карточки UI:
- Если есть deck_card — не перечисляй карты и не пиши про «ниже».
- Если есть battle/matchup карточка — не повторяй проценты и сухую статистику.
Текст дополняет карточку, не копирует её.

Инструменты вызывай молча. Ошибку инструмента — одной короткой фразой + альтернатива."""

# Лимиты слов по intent
WORD_LIMITS: dict[str, int] = {
    "card_info": 70,
    "last_battle": 90,
    "build_deck": 70,
    "matchup": 80,
    "analyze_deck": 100,
    "improve_deck": 100,
    "game_coach": 90,
    "explain_mechanic": 80,
    "clarify": 70,
    "unsupported": 60,
    "default": 90,
}

# Фразы, которых не должно быть в ответах игроку
BANNED_SNIPPETS = (
    "как ии",
    "как ai",
    "я искусственн",
    "языковая модель",
    "как нейросеть",
    "recommendationengine",
    "в качестве ии",
    "я видел реплей",
    "посмотрел реплей",
)

# Запрещённые тренерские штампы (вырезаем / заменяем)
BANNED_PHRASES: tuple[tuple[str, str], ...] = (
    ("колода показана ниже", ""),
    ("сама колода показана ниже", ""),
    ("показана ниже", ""),
    ("я собрал колоду", "Нашёл рабочую сборку"),
    ("я собрал", "Нашёл"),
    ("я взял за основу", "Рабочий вариант —"),
    ("я нашёл", "Нашёл"),
    ("попробуй другое ядро", "Уточни ключевую карту — соберём точнее"),
    ("нет шаблонов", "Соберу рабочий вариант под твою опору"),
    ("готовых шаблонов", "Готовой сборки"),
    ("дай ядро", "Напиши ключевую карту"),
    ("ядро из 4", "ключевую карту"),
    ("используй эту колоду", ""),
    ("вот список карт", ""),
    ("как видно", ""),
    ("как можно заметить", ""),
    ("рекомендую сыграть", ""),
    ("рекомендую", ""),
    ("следует", ""),
    ("стоит ", ""),
)

_FLATTERY_RE = re.compile(
    r"("
    r"отличн(ая|ый|ое|ые)\s+(колода|сборка|игра|выбор|пик)|"
    r"ты\s+(молодец|красавчик|гений|имба)|"
    r"гениальн(ый|ая|о)|"
    r"супер\s+(выбор|колода|игра)|"
    r"вау[,!]?\s*"
    r")",
    re.IGNORECASE,
)

_SCOLDING_RE = re.compile(
    r"("
    r"ты\s+туп|"
    r"играешь\s+ужас|"
    r"ну\s+как\s+можно|"
    r"это\s+детский\s+сад|"
    r"полный\s+провал|"
    r"безнадёжн|"
    r"бездарн"
    r")",
    re.IGNORECASE,
)

_GENERIC_FLUFF_RE = re.compile(
    r"("
    r"^в\s+целом[,:]?\s*|"
    r"^важно\s+(отметить|помнить|понимать)[,:]?\s*|"
    r"^следует\s+отметить[,:]?\s*|"
    r"^как\s+правило[,:]?\s*|"
    r"^стоит\s+учитывать[,:]?\s*|"
    r"^необходимо\s+понимать[,:]?\s*|"
    r"главное\s+[—\-–]\s*практика\.?|"
    r"смотри\s+по\s+ситуации\.?|"
    r"всё\s+зависит\s+от\s+контекста\.?"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def word_limit_for(intent: str | None) -> int:
    if not intent:
        return WORD_LIMITS["default"]
    return WORD_LIMITS.get(intent, WORD_LIMITS["default"])


def count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text or ""))


def trim_to_word_limit(text: str, limit: int) -> str:
    """Обрезать по предложениям, чтобы уложиться в лимит слов."""
    raw = (text or "").strip()
    if not raw or count_words(raw) <= limit:
        return raw
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(raw) if p.strip()]
    kept: list[str] = []
    for part in parts:
        candidate = " ".join(kept + [part]).strip()
        if count_words(candidate) > limit and kept:
            break
        kept.append(part)
        if count_words(" ".join(kept)) >= limit:
            break
    out = " ".join(kept).strip()
    if not out:
        words = re.findall(r"\S+", raw)
        out = " ".join(words[:limit])
    return out


def coach_reply(
    verdict: str,
    *,
    why: str = "",
    action: str = "",
    tip: str = "",
    archetype: str | None = None,
    intent: str | None = None,
    max_sentences: int = 4,
) -> str:
    """Короткий ответ тренера: вывод → объяснение → совет.

    `action` складывается в объяснение (совместимость), отдельным блоком не печатается.
    Совет — из аргумента или готового coach_tips.json.
    """
    v = (verdict or "").strip()
    explanation = " ".join(
        p.strip() for p in (why, action) if p and str(p).strip()
    ).strip()
    tip_text = (tip or "").strip() or pick_tip(archetype, seed=v or explanation)

    blocks: list[str] = []
    if v:
        blocks.append(v)
    if explanation:
        blocks.append(explanation)
    if tip_text and tip_text.lower() not in " ".join(blocks).lower():
        blocks.append(tip_text)

    sentences: list[str] = []
    for block in blocks:
        for part in _SENTENCE_SPLIT_RE.split(block):
            part = part.strip()
            if not part:
                continue
            sentences.append(part)
            if len(sentences) >= max_sentences:
                break
        if len(sentences) >= max_sentences:
            break

    # До 3 абзацев (вывод / why / tip), внутри уже обрезано по предложениям
    if len(blocks) <= 3 and len(sentences) <= max_sentences:
        # Пересобираем блоки, не превышая лимит предложений
        rebuilt: list[str] = []
        used = 0
        for block in blocks:
            block_sents = [p.strip() for p in _SENTENCE_SPLIT_RE.split(block) if p.strip()]
            take = block_sents[: max(0, max_sentences - used)]
            if take:
                rebuilt.append(" ".join(take))
                used += len(take)
            if used >= max_sentences:
                break
        text = "\n\n".join(rebuilt)
    else:
        text = "\n\n".join(sentences[:max_sentences])

    text = assert_coach_voice(text)
    text = trim_to_word_limit(text, word_limit_for(intent))
    return text or "Уточни задачу — дам точный совет."


def assert_coach_voice(text: str) -> str:
    """Зачистка: запреты, лесть, ругань, вода, глоссарий."""
    out = (text or "").strip()
    if not out:
        return out

    low = out.lower()
    for ban in BANNED_SNIPPETS:
        if ban in low:
            out = out.replace("Как ИИ", "").replace("как ИИ", "")
            out = out.replace("Как AI", "").replace("как AI", "")
            break

    for phrase, repl in BANNED_PHRASES:
        out = re.sub(re.escape(phrase), repl, out, flags=re.IGNORECASE)

    out = _FLATTERY_RE.sub("", out)
    out = _SCOLDING_RE.sub("", out)
    out = _GENERIC_FLUFF_RE.sub("", out)
    out = apply_glossary(out)

    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"^\s*[,:;.\-—–]+\s*", "", out, flags=re.MULTILINE)
    out = re.sub(r"\s+\n", "\n", out)
    out = re.sub(r"\n\n+", "\n\n", out)
    # обрывки после вырезания штампов: ". сыграть." / "  ."
    out = re.sub(r"\s*\.\s*\.", ".", out)
    out = re.sub(r"(^|\n)\s*[.!,;:]+\s*", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip(" \t\n.,;")


def ensure_coach_ending(text: str, *, tip: str = "", archetype: str | None = None) -> str:
    """Если ответа нет — короткий fallback. Не дописываем воду к готовым ответам."""
    raw = assert_coach_voice(text)
    if not raw:
        return coach_reply(
            "Нужен чуть более конкретный вопрос.",
            tip=tip or pick_tip(archetype),
            intent="clarify",
        )
    # Уже короткий ответ тренера — не раздуваем
    if count_words(raw) <= word_limit_for("default") and len(
        [s for s in _SENTENCE_SPLIT_RE.split(raw) if s.strip()]
    ) <= 4:
        return raw
    return trim_to_word_limit(raw, word_limit_for("default"))
