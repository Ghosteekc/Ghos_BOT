"""Meme / rofl deck presets — intentionally unplayable nonsense."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoflDeck:
    key: str
    name: str
    cards: tuple[str, ...]
    tagline: str


ROFL_DECKS: list[RoflDeck] = [
    RoflDeck(
        "funeral",
        "Похоронное бюро",
        ("Skeletons", "Skeleton Army", "Skeleton Barrel", "Skeleton Dragons",
         "Giant Skeleton", "Graveyard", "Tombstone", "Skeleton King"),
        "Только кости. R.I.P. королевская башня.",
    ),
    RoflDeck(
        "alaska",
        "Аляска",
        ("Ice Spirit", "Ice Golem", "Ice Wizard", "Giant Snowball",
         "Freeze", "Lumberjack", "Sparky", "Musketeer"),
        "Заморозили эликсир и мозги. Абсолютный ноль тактики.",
    ),
    RoflDeck(
        "goblin-corp",
        "Гоблин Inc.",
        ("Goblins", "Spear Goblins", "Goblin Gang", "Dart Goblin",
         "Goblin Barrel", "Goblin Hut", "Goblin Cage", "Goblin Drill"),
        "HR-отдел гоблинов одобрил эту колоду. Вы — нет.",
    ),
    RoflDeck(
        "spell-only",
        "Школа магии (без выпуска)",
        ("Zap", "Fireball", "Arrows", "Rocket", "Lightning",
         "Poison", "The Log", "Giant Snowball"),
        "8 заклинаний. Win condition — надежда и баги клиента.",
    ),
    RoflDeck(
        "buildings",
        "Застройщик",
        ("Cannon", "Tesla", "Inferno Tower", "Bomb Tower", "Tombstone",
         "Goblin Hut", "Goblin Cage", "Barbarian Hut"),
        "BRUTALISM: только постройки, войска запрещены.",
    ),
    RoflDeck(
        "royal-family",
        "Королевская семья",
        ("Prince", "Princess", "Dark Prince", "Royal Giant",
         "Royal Ghost", "Royal Hogs", "Royal Recruits", "Golden Knight"),
        "Династия в сборе. Бюджет на оборону — нулевой.",
    ),
    RoflDeck(
        "giants",
        "Клуб толстяков",
        ("Giant", "Royal Giant", "Goblin Giant", "Elixir Giant",
         "Electro Giant", "Giant Skeleton", "Mega Knight", "P.E.K.K.A"),
        "Медленно, дорого, красиво. Как понедельник.",
    ),
    RoflDeck(
        "hogs",
        "Свиноферма",
        ("Hog Rider", "Royal Hogs", "Battle Ram", "Wall Breakers",
         "Ram Rider", "Elite Barbarians", "Rage", "Zap"),
        "Все бегут к мосту. Защиты нет — это фича.",
    ),
    RoflDeck(
        "elixir-bank",
        "Копилка эликсира",
        ("Elixir Collector", "Elixir Golem", "Mirror", "Three Musketeers",
         "P.E.K.K.A", "Golem", "Giant", "Wizard"),
        "Копим эликсир, проигрываем быстрее.",
    ),
    RoflDeck(
        "sparky-fun",
        "Фейерверк",
        ("Sparky", "Rocket", "Lightning", "Fireball",
         "Zap", "Giant Snowball", "Arrows", "The Log"),
        "Sparky заряжается, пока вас уже трибушат.",
    ),
    RoflDeck(
        "fish",
        "Рыбный рынок",
        ("Fisherman", "Royal Giant", "Hunter", "Mega Minion",
         "Minions", "Bats", "Skeleton Dragons", "Baby Dragon"),
        "Рыбалка была ошибкой. В воздухе тоже.",
    ),
    RoflDeck(
        "mirror-chaos",
        "Зеркальный лабиринт",
        ("Mirror", "Clone", "Rage", "Freeze",
         "Tornado", "Zap", "The Log", "Giant Snowball"),
        "Зеркало + клон + ярость = шизофрения колоды.",
    ),
    RoflDeck(
        "barbarians",
        "Варварский YOLO",
        ("Barbarians", "Elite Barbarians", "Barbarian Hut", "Barbarian Barrel",
         "Rage", "Battle Ram", "Fireball", "Zap"),
        "RRRRRAGE! Мозг отключён, кнопки жмутся сами.",
    ),
    RoflDeck(
        "miner-spam",
        "Шахтёр на смене 24/7",
        ("Miner", "Goblin Drill", "Wall Breakers", "Skeletons",
         "Ice Spirit", "Zap", "The Log", "Fire Spirit"),
        "Копаем под ареной. Защиты арены — нет.",
    ),
]
