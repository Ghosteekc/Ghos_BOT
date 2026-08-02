"""Детект интента Ghosteek AI — закрытый набор, без угадывания."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bot.services.card_data import CARD_META
from bot.services.card_names_ru import CARD_NAMES_RU, CARD_NAMES_SHORT

# Intent → сервис (этап 1)
INTENT_BUILD_DECK = "build_deck"  # Builder
INTENT_ANALYZE_DECK = "analyze_deck"  # Analyzer
INTENT_IMPROVE_DECK = "improve_deck"  # Recommendation
INTENT_MATCHUP = "matchup"  # Matchup Analyzer
INTENT_LAST_BATTLE = "last_battle"  # Battle Analyzer
INTENT_CARD_INFO = "card_info"  # Card Database
INTENT_EXPLAIN_MECHANIC = "explain_mechanic"  # Knowledge Base
INTENT_GAME_COACH = "game_coach"  # Game Coach
INTENT_UNSUPPORTED = "unsupported"
INTENT_CLARIFY = "clarify"

# Совместимость со старыми тестами / API
INTENT_UNKNOWN = INTENT_CLARIFY
INTENT_STATS = "stats"  # вне этапа 1 → clarify
INTENT_META = "meta"  # вне этапа 1 → clarify

SERVICE_BY_INTENT: dict[str, str] = {
    INTENT_BUILD_DECK: "Builder",
    INTENT_ANALYZE_DECK: "Analyzer",
    INTENT_IMPROVE_DECK: "Recommendation",
    INTENT_MATCHUP: "Matchup Analyzer",
    INTENT_LAST_BATTLE: "Battle Analyzer",
    INTENT_CARD_INFO: "Card Database",
    INTENT_EXPLAIN_MECHANIC: "Knowledge Base",
    INTENT_GAME_COACH: "Game Coach",
    INTENT_UNSUPPORTED: "HonestFallback",
    INTENT_CLARIFY: "Clarify",
}

CLARIFY_PROMPT = (
    "Уточните, пожалуйста, что нужно:\n"
    "1) собрать колоду (Builder)\n"
    "2) разобрать колоду (Analyzer)\n"
    "3) улучшить колоду (Recommendation)\n"
    "4) разобрать матчап (Matchup Analyzer)\n"
    "5) разобрать мой бой (Battle Analyzer)\n"
    "6) объяснить карту (Card Database)\n"
    "7) объяснить механику — cycle, elixir trade и т.п. (Knowledge Base)\n"
    "8) совет — кубки, как играть против архетипа (Game Coach)\n"
    "Не буду угадывать — напишите цель запроса."
)


@dataclass
class DetectedIntent:
    intent: str
    cards: list[str] = field(default_factory=list)
    opponent_cards: list[str] = field(default_factory=list)
    card_query: str | None = None
    mechanic_query: str | None = None
    coach_topic: str | None = None
    service: str = ""
    raw: str = ""

    def __post_init__(self) -> None:
        if not self.service:
            self.service = SERVICE_BY_INTENT.get(self.intent, "Clarify")


def _build_alias_index() -> list[tuple[str, str]]:
    """(alias_lower, english_name), longest first."""
    pairs: dict[str, str] = {}
    for en in CARD_META:
        pairs[en.lower()] = en
    for en, ru in CARD_NAMES_RU.items():
        pairs[ru.lower()] = en
        pairs[en.lower()] = en
    for en, ru in CARD_NAMES_SHORT.items():
        pairs[ru.lower()] = en
    extras = {
        "хог": "Hog Rider",
        "хога": "Hog Rider",
        "хогом": "Hog Rider",
        "хогу": "Hog Rider",
        "hog": "Hog Rider",
        "пекка": "P.E.K.K.A",
        "pekka": "P.E.K.K.A",
        "мини пекка": "Mini P.E.K.K.A",
        "фаербол": "Fireball",
        "файрбол": "Fireball",
        "торнадо": "Tornado",
        "палач": "Executioner",
        "палача": "Executioner",
        "лава": "Lava Hound",
        "лавы": "Lava Hound",
        "шарик": "Balloon",
        "шарика": "Balloon",
        "шар": "Balloon",
        "бочка": "Goblin Barrel",
        "бочку": "Goblin Barrel",
        "принцесса": "Princess",
        "принцессу": "Princess",
        "логи": "The Log",
        "бревно": "The Log",
        "лог": "The Log",
        "землетряс": "Earthquake",
        "eq": "Earthquake",
        "lavaloon": "Lava Hound",
        "лавалун": "Lava Hound",
    }
    for alias, en in extras.items():
        pairs.setdefault(alias, en)
    return sorted(pairs.items(), key=lambda x: len(x[0]), reverse=True)


_ALIAS_INDEX = _build_alias_index()

_UNSUPPORTED_RE = re.compile(
    r"("
    r"урон\s+по\s+карт|"
    r"сколько\s+урона|"
    r"damage\s+per|"
    r"эликсир(а|у)?\s+в\s+рук|"
    r"сколько\s+эликсир|"
    r"elixir\s+in\s+hand|"
    r"hp\s+башн|"
    r"точн(ый|ое)\s+хп|"
    r"кадры\s+боя|"
    r"replay\s+frame"
    r")",
    re.IGNORECASE,
)

# Механики Knowledge Base: (aliases…) → key
_MECHANIC_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("positive elixir trade", "позитивн", "плюс по эликсир", "+elixir", "эликсир трейд"), "positive_elixir_trade"),
    (("negative elixir trade", "негативн", "минус по эликсир"), "negative_elixir_trade"),
    (("elixir trade", "trade эликсир", "обмен эликсир"), "elixir_trade"),
    (("dual lane", "две линии", "давление на две", "double lane"), "dual_lane_pressure"),
    (("bridge spam", "бридж спам", "спам с моста"), "bridge_spam"),
    (("cycle", "цикл колоды", "быстрый цикл", "card cycle"), "cycle"),
    (("beatdown", "битдаун"), "beatdown"),
    (("control", "контроль"), "control"),
    (("bait", "бейт", "log bait"), "bait"),
    (("spell cycle", "спелл цикл"), "spell_cycle"),
    (("kiting", "кайт", "kite"), "kiting"),
    (("tank", "танк"), "tank"),
]


def extract_cards_from_text(text: str, *, limit: int = 16) -> list[str]:
    """Жадный матч по самым длинным алиасам без пересечений."""
    low = text.lower()
    found: list[str] = []
    occupied = [False] * len(low)
    for alias, en in _ALIAS_INDEX:
        if not alias:
            continue
        start = 0
        while True:
            idx = low.find(alias, start)
            if idx < 0:
                break
            end = idx + len(alias)
            before_ok = idx == 0 or not low[idx - 1].isalnum()
            after_ok = end >= len(low) or not low[end].isalnum()
            if before_ok and after_ok and not any(occupied[idx:end]):
                if en not in found:
                    found.append(en)
                for i in range(idx, end):
                    occupied[i] = True
                if len(found) >= limit:
                    return found
            start = idx + 1
    return found


def _match_mechanic(low: str) -> str | None:
    for aliases, key in _MECHANIC_ALIASES:
        if any(a in low for a in aliases):
            return key
    return None


def detect_intent(message: str, *, context_cards: list[str] | None = None) -> DetectedIntent:
    """Rule-based intent. Если сигнал слабый — clarify, не угадывать."""
    raw = (message or "").strip()
    low = raw.lower()
    extracted = extract_cards_from_text(raw)
    ctx = [c for c in (context_cards or []) if c]

    def _out(
        intent: str,
        *,
        cards: list[str] | None = None,
        opponent_cards: list[str] | None = None,
        card_query: str | None = None,
        mechanic_query: str | None = None,
        coach_topic: str | None = None,
    ) -> DetectedIntent:
        return DetectedIntent(
            intent=intent,
            cards=cards if cards is not None else extracted,
            opponent_cards=opponent_cards or [],
            card_query=card_query,
            mechanic_query=mechanic_query,
            coach_topic=coach_topic,
            raw=raw,
        )

    if not raw:
        return _out(INTENT_CLARIFY, cards=ctx[:8])

    if _UNSUPPORTED_RE.search(low):
        return _out(INTENT_UNSUPPORTED, cards=extracted or ctx[:8])

    # --- Battle Analyzer ---
    if any(
        k in low
        for k in (
            "последн",
            "прошл",
            "почему проигр",
            "разбор боя",
            "разбери бой",
            "разбери мой бой",
            "этот бой",
            "мой бой",
        )
    ):
        return _out(INTENT_LAST_BATTLE)

    # --- Knowledge Base (механики) — до «против», чтобы не путать ---
    mechanic = _match_mechanic(low)
    if mechanic and any(
        k in low
        for k in ("что такое", "что значит", "объясни", "означает", "что есть", "what is", "mechanic")
    ):
        return _out(INTENT_EXPLAIN_MECHANIC, mechanic_query=mechanic)
    if mechanic and re.search(r"\b(cycle|bait|beatdown|bridge\s*spam|elixir\s*trade)\b", low):
        # Короткие EN-термины без глагола — тоже Knowledge Base
        if not any(k in low for k in ("собери", "разбер", "улучш", "матчап", "против", "апнуть")):
            return _out(INTENT_EXPLAIN_MECHANIC, mechanic_query=mechanic)

    # --- Game Coach ---
    if any(
        k in low
        for k in (
            "как апнуть",
            "апнуть куб",
            "набрать куб",
            "поднять куб",
            "как поднять троф",
            "как фармить",
            "посоветуй",
            "дай совет",
            "как играть против",
            "как против",
            "чем бить",
            "как контрить",
        )
    ):
        topic = "climb" if any(k in low for k in ("куб", "троф", "апнуть", "фарм")) else "vs_advice"
        if topic == "vs_advice" and not any(k in low for k in ("против", "контр", "бить")):
            topic = "general"
        return _out(INTENT_GAME_COACH, cards=extracted or ctx[:8], coach_topic=topic)

    # --- Matchup Analyzer ---
    if any(k in low for k in ("матчап", "разбери матчап", "против колоды", " vs ", " vs")):
        user_cards = ctx[:8] if len(ctx) >= 8 else extracted[:8]
        opp = (
            extracted[8:16]
            if len(extracted) >= 16
            else (extracted if len(ctx) >= 8 else extracted[4:12])
        )
        return _out(INTENT_MATCHUP, cards=user_cards, opponent_cards=opp)

    # --- Builder ---
    if any(
        k in low
        for k in (
            "собери",
            "построй",
            "конструктор",
            "хочу играть через",
            "играть через",
            "колоду через",
            "вокруг",
        )
    ):
        core = extracted[:4] or ctx[:4]
        return _out(INTENT_BUILD_DECK, cards=core)

    # --- Recommendation ---
    if any(k in low for k in ("улучш", "замен", "что помен", "что смен", "фикс колоды")):
        cards = extracted[:8] if len(extracted) >= 4 else (ctx[:8] if ctx else extracted)
        return _out(INTENT_IMPROVE_DECK, cards=cards)

    # --- Analyzer (явный разбор колоды) ---
    if any(
        k in low
        for k in (
            "разбери колоду",
            "разбор колоды",
            "анализ колоды",
            "проверь колоду",
            "оцени колоду",
            "паспорт колоды",
            "паспорт",
        )
    ) or (
        "разбер" in low and "колод" in low
    ):
        cards = extracted[:8] if len(extracted) >= 4 else (ctx[:8] if ctx else extracted)
        return _out(INTENT_ANALYZE_DECK, cards=cards)

    # --- Card Database ---
    if any(
        k in low
        for k in (
            "что за карта",
            "что делает",
            "роль карты",
            "про карту",
            "объясни карту",
            "расскажи про карту",
        )
    ) or (len(extracted) == 1 and any(k in low for k in ("карта", "карт"))):
        q = extracted[0] if extracted else None
        return _out(INTENT_CARD_INFO, cards=extracted, card_query=q)

    # Голые «что такое …» без известной механики — Knowledge Base miss → clarify
    if any(k in low for k in ("что такое", "что значит", "объясни механику")):
        return _out(INTENT_EXPLAIN_MECHANIC, mechanic_query=None)

    # Не угадываем по одним картам / мета / винрейт вне этапа 1
    return _out(INTENT_CLARIFY, cards=extracted or ctx[:8])
