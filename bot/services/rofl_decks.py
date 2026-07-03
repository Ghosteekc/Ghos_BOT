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
        "Только кости. Покойся с миром, королевская башня.",
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
        "ООО «Гоблин»",
        ("Goblins", "Spear Goblins", "Goblin Gang", "Dart Goblin",
         "Goblin Barrel", "Goblin Hut", "Goblin Cage", "Goblin Drill"),
        "Отдел кадров гоблинов одобрил. Вы — нет.",
    ),
    RoflDeck(
        "spell-only",
        "Школа магии (без выпуска)",
        ("Zap", "Fireball", "Arrows", "Rocket", "Lightning",
         "Poison", "The Log", "Giant Snowball"),
        "8 заклинаний. Условие победы — надежда и баги клиента.",
    ),
    RoflDeck(
        "buildings",
        "Застройщик",
        ("Cannon", "Tesla", "Inferno Tower", "Bomb Tower", "Tombstone",
         "Goblin Hut", "Goblin Cage", "Barbarian Hut"),
        "Только бетон и башни. Войска запрещены.",
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
        ("Giant", "Royal Giant", "Goblin Giant", "Rune Giant",
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
        "Спарки заряжается, пока вас уже три раза законтрили.",
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
        "Варварский рывок",
        ("Barbarians", "Elite Barbarians", "Barbarian Hut", "Barbarian Barrel",
         "Rage", "Battle Ram", "Fireball", "Zap"),
        "Ярость включена. Мозг отключён, кнопки жмутся сами.",
    ),
    RoflDeck(
        "miner-spam",
        "Шахтёр на смене 24/7",
        ("Miner", "Goblin Drill", "Wall Breakers", "Skeletons",
         "Ice Spirit", "Zap", "The Log", "Fire Spirit"),
        "Копаем под ареной. Защиты арены — нет.",
    ),
    RoflDeck(
        "spirit-shop",
        "Духовная лавка",
        ("Ice Spirit", "Fire Spirit", "Electro Spirit", "Heal Spirit",
         "Ice Wizard", "Wizard", "Electro Wizard", "Freeze"),
        "Восьмеро духов и магов. Атмосфера — холодильник на максимум.",
    ),
    RoflDeck(
        "witch-coven",
        "Шабаш ведьм",
        ("Witch", "Night Witch", "Mother Witch", "Wizard",
         "Ice Wizard", "Electro Wizard", "Fireball", "Tornado"),
        "Собрали всех колдунов. Баланс команды — миф.",
    ),
    RoflDeck(
        "sky-zoo",
        "Весь воздух",
        ("Balloon", "Minions", "Minion Horde", "Bats",
         "Skeleton Dragons", "Baby Dragon", "Mega Minion", "Lava Hound"),
        "Ни одной наземной карты. Земля для слабаков.",
    ),
    RoflDeck(
        "one-elixir",
        "Клуб одного эликсира",
        ("Skeletons", "Ice Spirit", "Fire Spirit", "Electro Spirit",
         "Heal Spirit", "Bats", "Spear Goblins", "Goblins"),
        "Дёшево, быстро, бессмысленно. Как распродажа в ларьке.",
    ),
    RoflDeck(
        "logs-and-rocks",
        "Бревна и камни",
        ("The Log", "Barbarian Barrel", "Giant Snowball", "Royal Delivery",
         "Earthquake", "Poison", "Arrows", "Zap"),
        "Заклинания летят, армии нет. Просто кидаем предметы в короля.",
    ),
    RoflDeck(
        "shock-therapy",
        "Электрошок",
        ("Electro Wizard", "Electro Dragon", "Electro Giant", "Electro Spirit",
         "Lightning", "Sparky", "Tesla", "Zap"),
        "Током бьёт и по вам, и по врагу. Главное — шумно.",
    ),
    RoflDeck(
        "champion-parade",
        "Парад чемпионов",
        ("Skeleton King", "Archer Queen", "Golden Knight", "Mighty Miner",
         "Monk", "Little Prince", "Bandit", "Magic Archer"),
        "Только элита. Обычные карты обиделись и ушли.",
    ),
    RoflDeck(
        "pekka-party",
        "Вечеринка П.E.K.K.A",
        ("P.E.K.K.A", "Mini P.E.K.K.A", "Mega Knight", "Prince",
         "Dark Prince", "Valkyrie", "Wizard", "Arrows"),
        "Тяжёлая пехота без мозгов. Зато блестят.",
    ),
    RoflDeck(
        "grave-shift",
        "Ночная смена на кладбище",
        ("Graveyard", "Tombstone", "Skeletons", "Skeleton Army",
         "Poison", "Freeze", "Tornado", "Ice Wizard"),
        "Ночью скелеты работают, днём вы проигрываете.",
    ),
    RoflDeck(
        "defense-zero",
        "Нулевая оборона",
        ("Hog Rider", "Balloon", "Giant", "Golem",
         "Royal Hogs", "Wall Breakers", "Battle Ram", "Miner"),
        "Только атака. Защиты не существует — это стратегия.",
    ),
    RoflDeck(
        "boom-boom",
        "Бум-бум отдел",
        ("Rocket", "Fireball", "Lightning", "Poison",
         "Giant Snowball", "Zap", "Arrows", "Earthquake"),
        "Взрываем всё подряд. Свои башни тоже в зоне риска.",
    ),
    RoflDeck(
        "sneaky-sneaky",
        "Тихая ганг",
        ("Miner", "Goblin Drill", "Royal Ghost", "Bandit",
         "Wall Breakers", "Skeleton Barrel", "Goblin Barrel", "Dart Goblin"),
        "Никто не видит, все проигрывают. Идеальный стелс.",
    ),
    RoflDeck(
        "knight-school",
        "Рыцарская школа",
        ("Knight", "Golden Knight", "Mega Knight", "Dark Prince",
         "Prince", "Valkyrie", "Guards", "Barbarians"),
        "Урок этикета отменён. Остались только удары мечом.",
    ),
    RoflDeck(
        "dragon-den",
        "Логово драконов",
        ("Baby Dragon", "Inferno Dragon", "Electro Dragon", "Skeleton Dragons",
         "Lava Hound", "Balloon", "Freeze", "Arrows"),
        "Драконы, огонь и надежда. Защиты по-прежнему нет.",
    ),
]
