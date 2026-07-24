"""Рофл-колоды: готовые абсурдные шаблоны. Не смешивать с обычным рандомом."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoflDeck:
    """Шаблон рофл-колоды: название, подпись и ровно 8 уникальных карт."""

    key: str
    name: str
    cards: tuple[str, ...]
    tagline: str
    concept: str = ""


# Минимум 20 уникальных концептов. Карты — только реальные имена из CARD_META.
ROFL_DECKS: list[RoflDeck] = [
    RoflDeck(
        key="alaska",
        name="Аляска",
        cards=(
            "Ice Wizard",
            "Ice Golem",
            "Ice Spirit",
            "Freeze",
            "Giant Snowball",
            "Mega Knight",
            "Wizard",
            "Tesla",
        ),
        tagline="холодно? нет, это просто ты плохо играешь",
        concept="мороз и лёд",
    ),
    RoflDeck(
        key="funeral-home",
        name="Похоронное бюро",
        cards=(
            "Graveyard",
            "Giant Skeleton",
            "Skeleton Army",
            "Skeleton Barrel",
            "Skeleton Dragons",
            "Tombstone",
            "Guards",
            "Skeleton King",
        ),
        tagline="клиент всегда мёртв",
        concept="скелеты и кладбище",
    ),
    RoflDeck(
        key="developer",
        name="Застройщик",
        cards=(
            "X-Bow",
            "Mortar",
            "Inferno Tower",
            "Tesla",
            "Cannon",
            "Tombstone",
            "Goblin Cage",
            "Elixir Collector",
        ),
        tagline="ипотека 0% годовых, но эликсир заберём",
        concept="максимум построек",
    ),
    RoflDeck(
        key="swamp-escape",
        name="Побег с болота",
        cards=(
            "Goblin Barrel",
            "Dart Goblin",
            "Goblin Gang",
            "Goblin Hut",
            "Goblin Cage",
            "Goblin Drill",
            "Spear Goblins",
            "Goblins",
        ),
        tagline="они не сбежали. они просто пошли за тобой",
        concept="только гоблины",
    ),
    RoflDeck(
        key="just-looking",
        name="Я просто посмотреть",
        cards=(
            "Mirror",
            "Clone",
            "Rage",
            "Freeze",
            "Heal Spirit",
            "Tornado",
            "Zap",
            "The Log",
        ),
        tagline="план был хороший до первого хода",
        concept="заклинания без плана",
    ),
    RoflDeck(
        key="elixir-gone",
        name="Эликсир закончился",
        cards=(
            "Three Musketeers",
            "Golem",
            "P.E.K.K.A",
            "Electro Giant",
            "Lava Hound",
            "Sparky",
            "Mega Knight",
            "Elixir Collector",
        ),
        tagline="скилл issue",
        concept="всё слишком дорого",
    ),
    RoflDeck(
        key="who-let-them-in",
        name="Кто пустил этих людей",
        cards=(
            "Wizard",
            "Witch",
            "Bomber",
            "Firecracker",
            "Archers",
            "Spear Goblins",
            "Dart Goblin",
            "Princess",
        ),
        tagline="ой они снова стреляют",
        concept="всех раздражает",
    ),
    RoflDeck(
        key="mom-said-yes",
        name="Мама сказала можно",
        cards=(
            "Mega Knight",
            "Elite Barbarians",
            "Wizard",
            "Rage",
            "Freeze",
            "Mirror",
            "Fireball",
            "Minion Horde",
        ),
        tagline="мама не видела мету",
        concept="детский хаос",
    ),
    RoflDeck(
        key="mixed-salad",
        name="Сборная солянка",
        cards=(
            "Hog Rider",
            "X-Bow",
            "Graveyard",
            "Golem",
            "Goblin Barrel",
            "Lava Hound",
            "Mortar",
            "Wall Breakers",
        ),
        tagline="восемь винкондишенов. почему нет",
        concept="случайный винегрет винкондишенов",
    ),
    RoflDeck(
        key="bro-its-meta",
        name="Братан, это мета",
        cards=(
            "Elite Barbarians",
            "Wizard",
            "Witch",
            "Skeleton Army",
            "Minion Horde",
            "Fireball",
            "Zap",
            "Rage",
        ),
        tagline="это должно было сработать",
        concept="фейковая мета 2016",
    ),
    RoflDeck(
        key="everything-flies",
        name="Всё летает",
        cards=(
            "Lava Hound",
            "Balloon",
            "Minion Horde",
            "Baby Dragon",
            "Skeleton Dragons",
            "Inferno Dragon",
            "Mega Minion",
            "Bats",
        ),
        tagline="пво? а что это",
        concept="воздушный цирк",
    ),
    RoflDeck(
        key="spam-folder",
        name="Папка «Спам»",
        cards=(
            "Skeleton Army",
            "Goblin Gang",
            "Minion Horde",
            "Bats",
            "Skeletons",
            "Spear Goblins",
            "Wall Breakers",
            "Fire Spirit",
        ),
        tagline="inbox (999+)",
        concept="максимальный спам",
    ),
    RoflDeck(
        key="too-slow",
        name="Слишком медленно",
        cards=(
            "Golem",
            "Lava Hound",
            "Giant",
            "Electro Giant",
            "P.E.K.K.A",
            "Sparky",
            "Giant Skeleton",
            "Elixir Collector",
        ),
        tagline="план: отсутствует",
        concept="максимально медленные карты",
    ),
    RoflDeck(
        key="two-elixir-dream",
        name="Два эликсира и мечта",
        cards=(
            "Skeletons",
            "Bats",
            "Ice Spirit",
            "Fire Spirit",
            "Electro Spirit",
            "Heal Spirit",
            "Wall Breakers",
            "Zap",
        ),
        tagline="я не проиграл, я провёл тестирование",
        concept="всё слишком дешёвое",
    ),
    RoflDeck(
        key="one-does-work",
        name="Один работает",
        cards=(
            "Hog Rider",
            "Ice Spirit",
            "Skeletons",
            "Heal Spirit",
            "Bomber",
            "Archers",
            "Cannon",
            "Zap",
        ),
        tagline="остальные морально поддерживают",
        concept="одна карта тащит",
    ),
    RoflDeck(
        key="they-run",
        name="Они убегают",
        cards=(
            "Bandit",
            "Royal Ghost",
            "Wall Breakers",
            "Skeleton Barrel",
            "Miner",
            "Goblin Barrel",
            "Dart Goblin",
            "The Log",
        ),
        tagline="догони если сможешь",
        concept="все будто пытаются убежать",
    ),
    RoflDeck(
        key="fire-only",
        name="Горит всё",
        cards=(
            "Fireball",
            "Fire Spirit",
            "Furnace",
            "Inferno Tower",
            "Inferno Dragon",
            "Phoenix",
            "Wizard",
            "Lava Hound",
        ),
        tagline="туши не туши",
        concept="огонь и точка",
    ),
    RoflDeck(
        key="generator-error",
        name="Ошибка генератора",
        cards=(
            "Mirror",
            "Clone",
            "Heal Spirit",
            "Elixir Collector",
            "Suspicious Bush",
            "Goblin Curse",
            "Berserker",
            "Cannon",
        ),
        tagline="это баг. оставь",
        concept="выглядит как ошибка генератора",
    ),
    RoflDeck(
        key="not-invited",
        name="Не позвали",
        cards=(
            "Bomber",
            "Spear Goblins",
            "Ice Golem",
            "Heal Spirit",
            "Battle Healer",
            "Furnace",
            "Tombstone",
            "Barbarian Barrel",
        ),
        tagline="люди, которых не позвали на вечеринку",
        concept="аутсайдеры колоды",
    ),
    RoflDeck(
        key="random-8",
        name="Я нажал рандом",
        cards=(
            "Knight",
            "Archers",
            "Minions",
            "Arrows",
            "Giant",
            "Witch",
            "Baby Dragon",
            "Fireball",
        ),
        tagline="я серьёзно не выбирал",
        concept="классический новичок-рандом",
    ),
    RoflDeck(
        key="pick-one-card",
        name="Можно только одну",
        cards=(
            "Sparky",
            "Mirror",
            "Clone",
            "Rage",
            "Freeze",
            "Zap",
            "The Log",
            "Heal Spirit",
        ),
        tagline="родители сказали выбрать только одну карту",
        concept="спарки и моральная поддержка",
    ),
    RoflDeck(
        key="annoying-pack",
        name="Раздражающий пакет",
        cards=(
            "Royal Delivery",
            "Royal Recruits",
            "Royal Ghost",
            "Royal Hogs",
            "Fisherman",
            "Tornado",
            "Earthquake",
            "Goblin Curse",
        ),
        tagline="мут. репорт. мут",
        concept="максимально раздражающие карты",
    ),
    RoflDeck(
        key="almost-meta",
        name="Ну почти мета",
        cards=(
            "Hog Rider",
            "Ice Golem",
            "Musketeer",
            "Cannon",
            "Fireball",
            "The Log",
            "Skeletons",
            "Ice Spirit",
        ),
        tagline="выглядит умно. не работает",
        concept="почти нормальная колода, но нет",
    ),
    RoflDeck(
        key="trust-the-process",
        name="Просто поверь",
        cards=(
            "Balloon",
            "Freeze",
            "Rage",
            "Clone",
            "Lumberjack",
            "Inferno Dragon",
            "Barbarian Barrel",
            "Bats",
        ),
        tagline="trust the process (не надо)",
        concept="лофт-баллун на чистом угаре",
    ),
]


def validate_rofl_deck_shapes(decks: list[RoflDeck] | None = None) -> list[str]:
    """Статическая проверка шаблонов (без каталога карт)."""
    errors: list[str] = []
    seen_keys: set[str] = set()
    for deck in decks if decks is not None else ROFL_DECKS:
        if deck.key in seen_keys:
            errors.append(f"duplicate key: {deck.key}")
        seen_keys.add(deck.key)
        if not deck.name.strip():
            errors.append(f"{deck.key}: empty name")
        if not deck.tagline.strip():
            errors.append(f"{deck.key}: empty tagline")
        if len(deck.cards) != 8:
            errors.append(f"{deck.key}: expected 8 cards, got {len(deck.cards)}")
        if len(set(deck.cards)) != len(deck.cards):
            errors.append(f"{deck.key}: duplicate cards inside deck")
        if any(not c.strip() for c in deck.cards):
            errors.append(f"{deck.key}: empty card name")
    return errors
