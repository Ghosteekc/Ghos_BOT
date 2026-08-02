"""Game Coach: советы только из кураторских tip'ов и существующих сервисов."""

from __future__ import annotations

from bot.services.meta_decks import META_DECKS


# Архетипы для «как играть против X» → эталонная колода из META_DECKS
_ARCHETYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "lavaloon": ("lava-loon",),
    "lava loon": ("lava-loon",),
    "лавалун": ("lava-loon",),
    "лава лун": ("lava-loon",),
    "hog": ("hog-26",),
    "хог": ("hog-26",),
    "2.6": ("hog-26",),
    "bait": ("log-bait",),
    "бейт": ("log-bait",),
    "xbow": ("xbow-30",),
    "арбалет": ("xbow-30",),
    "golem": ("golem-nw",),
    "голем": ("golem-nw",),
}


CLIMB_TIPS: tuple[str, ...] = (
    "Играй одну колоду пачкой боёв — так стабильнее решения и цикл.",
    "После серии поражений сначала разбери последний бой, не меняй всё сразу.",
    "Слабые матчапы готовь заранее — в бою уже поздно паниковать.",
    "Если колода «не заходит» — сначала точечная замена, потом полная пересборка.",
    "Держи уровни карт под свой диапазон кубков — иначе тактика не спасёт.",
)


def resolve_archetype_deck(text: str) -> tuple[str, list[str]] | None:
    """Вернуть (название, 8 карт) из META_DECKS по алиасу в тексте."""
    low = (text or "").lower()
    keys: list[str] = []
    for alias, meta_keys in _ARCHETYPE_ALIASES.items():
        if alias in low:
            keys.extend(meta_keys)
    if not keys:
        return None
    by_key = {d.key: d for d in META_DECKS}
    for key in keys:
        deck = by_key.get(key)
        if deck and len(deck.cards) == 8:
            return deck.name, list(deck.cards)
    return None


def decks_for_win_condition(card: str, *, limit: int = 3) -> list[dict]:
    """Готовые меты/шаблоны, где есть карта — для Builder при «через Хога»."""
    out: list[dict] = []
    for d in META_DECKS:
        if card in d.cards:
            out.append({
                "name": d.name,
                "key": d.key,
                "cards": list(d.cards),
                "category": d.category,
                "description": d.description,
            })
        if len(out) >= limit:
            break
    return out
