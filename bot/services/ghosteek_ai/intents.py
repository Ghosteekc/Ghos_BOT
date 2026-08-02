"""Детект интента и извлечение карт из текста игрока."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bot.services.card_data import CARD_META
from bot.services.card_names_ru import CARD_NAMES_RU, CARD_NAMES_SHORT

INTENT_ANALYZE_DECK = "analyze_deck"
INTENT_IMPROVE_DECK = "improve_deck"
INTENT_BUILD_DECK = "build_deck"
INTENT_MATCHUP = "matchup"
INTENT_LAST_BATTLE = "last_battle"
INTENT_STATS = "stats"
INTENT_META = "meta"
INTENT_CARD_INFO = "card_info"
INTENT_UNSUPPORTED = "unsupported"
INTENT_UNKNOWN = "unknown"


@dataclass
class DetectedIntent:
    intent: str
    cards: list[str] = field(default_factory=list)
    opponent_cards: list[str] = field(default_factory=list)
    card_query: str | None = None
    raw: str = ""


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
    # Частые сленговые варианты
    extras = {
        "хог": "Hog Rider",
        "hog": "Hog Rider",
        "пекка": "P.E.K.K.A",
        "pekka": "P.E.K.K.A",
        "мини пекка": "Mini P.E.K.K.A",
        "фаербол": "Fireball",
        "файрбол": "Fireball",
        "торнадо": "Tornado",
        "палач": "Executioner",
        "лава": "Lava Hound",
        "шарик": "Balloon",
        "шар": "Balloon",
        "бочка": "Goblin Barrel",
        "принцесса": "Princess",
        "логи": "The Log",
        "бревно": "The Log",
        "лог": "The Log",
        "землетряс": "Earthquake",
        "eq": "Earthquake",
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
            # Границы слова / разделители
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


def detect_intent(message: str, *, context_cards: list[str] | None = None) -> DetectedIntent:
    raw = (message or "").strip()
    low = raw.lower()
    extracted = extract_cards_from_text(raw)
    ctx = [c for c in (context_cards or []) if c]

    if _UNSUPPORTED_RE.search(low):
        return DetectedIntent(intent=INTENT_UNSUPPORTED, cards=extracted or ctx[:8], raw=raw)

    if any(k in low for k in ("последн", "прошл", "почему проигр", "разбор боя", "этот бой")):
        return DetectedIntent(intent=INTENT_LAST_BATTLE, cards=extracted, raw=raw)

    if any(k in low for k in ("матчап", "против колоды", " vs ", " vs")) or (
        "против" in low and len(extracted) >= 2
    ):
        user_cards = ctx[:8] if len(ctx) >= 8 else extracted[:8]
        opp = extracted[8:16] if len(extracted) >= 16 else (
            extracted if len(ctx) >= 8 else extracted[4:12]
        )
        return DetectedIntent(
            intent=INTENT_MATCHUP,
            cards=user_cards,
            opponent_cards=opp,
            raw=raw,
        )

    if any(k in low for k in ("собери", "построй", "конструктор", "вокруг")):
        core = extracted[:4] or ctx[:4]
        return DetectedIntent(intent=INTENT_BUILD_DECK, cards=core, raw=raw)

    if any(k in low for k in ("улучш", "замен", "что помен", "что смен", "fixкс колоды")):
        cards = extracted[:8] if len(extracted) >= 4 else (ctx[:8] if ctx else extracted)
        return DetectedIntent(intent=INTENT_IMPROVE_DECK, cards=cards, raw=raw)

    if any(k in low for k in ("разбер", "анализ колоды", "проверь колоду", "оцени колоду", "паспорт")):
        cards = extracted[:8] if len(extracted) >= 4 else (ctx[:8] if ctx else extracted)
        return DetectedIntent(intent=INTENT_ANALYZE_DECK, cards=cards, raw=raw)

    if any(k in low for k in ("винрейт", "статистик", "мои бои", "сколько побед", "winrate")):
        return DetectedIntent(intent=INTENT_STATS, cards=extracted, raw=raw)

    if any(k in low for k in ("мета", "мете", "мету", "метой", "топ колод", "что играют", "meta")):
        return DetectedIntent(intent=INTENT_META, cards=extracted, raw=raw)

    if any(k in low for k in ("что за карта", "что делает", "роль карты", "про карту")) or (
        len(extracted) == 1 and any(k in low for k in ("карта", "карт"))
    ):
        q = extracted[0] if extracted else None
        return DetectedIntent(intent=INTENT_CARD_INFO, cards=extracted, card_query=q, raw=raw)

    # Если передали 8 карт в контексте без явного глагола — разбор колоды.
    if len(ctx) >= 8 or len(extracted) >= 8:
        cards = ctx[:8] if len(ctx) >= 8 else extracted[:8]
        return DetectedIntent(intent=INTENT_ANALYZE_DECK, cards=cards, raw=raw)

    if len(extracted) == 1:
        return DetectedIntent(
            intent=INTENT_CARD_INFO,
            cards=extracted,
            card_query=extracted[0],
            raw=raw,
        )

    return DetectedIntent(intent=INTENT_UNKNOWN, cards=extracted or ctx[:8], raw=raw)
