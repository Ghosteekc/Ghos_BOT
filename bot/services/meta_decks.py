"""Curated meta/popular decks (card names must match Clash Royale API)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MetaDeck:
    key: str
    name: str
    category: str  # meta | control | beatdown | cycle | bait
    cards: tuple[str, ...]
    description: str = ""


META_DECKS: list[MetaDeck] = [
    MetaDeck(
        "hog-26",
        "Хог 2.6",
        "cycle",
        ("Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"),
        "Классический быстрый цикл с хогом",
    ),
    MetaDeck(
        "log-bait",
        "Бейт",
        "bait",
        ("Goblin Barrel", "Princess", "Goblin Gang", "Ice Spirit", "Knight", "Inferno Tower", "Rocket", "The Log"),
        "Провокация заклинаний и гоблинская бочка",
    ),
    MetaDeck(
        "xbow-30",
        "Арбалет 3.0",
        "control",
        ("X-Bow", "Tesla", "Archers", "Ice Spirit", "Skeletons", "Fireball", "The Log", "Knight"),
        "Контроль с арбалетом и теслой",
    ),
    MetaDeck(
        "giant-dprince",
        "Гигант + принцы",
        "beatdown",
        ("Giant", "Dark Prince", "Prince", "Miner", "Musketeer", "Electro Wizard", "Poison", "Zap"),
        "Битдаун с двойным принцем",
    ),
    MetaDeck(
        "rg-fish",
        "Королевский гигант",
        "meta",
        ("Royal Giant", "Fisherman", "Hunter", "Fireball", "Lightning", "Electro Spirit", "Skeletons", "Cannon"),
        "Королевский гигант с рыбаком",
    ),
    MetaDeck(
        "pekka-bs",
        "Пекка мост",
        "meta",
        ("P.E.K.K.A", "Battle Ram", "Bandit", "Royal Ghost", "Magic Archer", "Electro Wizard", "Poison", "Zap"),
        "Мостовой спам вокруг пекки",
    ),
    MetaDeck(
        "lava-loon",
        "Лава-Loon",
        "beatdown",
        ("Lava Hound", "Balloon", "Mega Minion", "Tombstone", "Guards", "Arrows", "Lightning", "Barbarian Barrel"),
        "Воздушный битдаун",
    ),
    MetaDeck(
        "golem-nw",
        "Голем + ночная ведьма",
        "beatdown",
        ("Golem", "Night Witch", "Baby Dragon", "Mega Minion", "Lumberjack", "Tornado", "Lightning", "Barbarian Barrel"),
        "Классический голем-пуш",
    ),
    MetaDeck(
        "mortar-cycle",
        "Мортира цикл",
        "cycle",
        ("Mortar", "Knight", "Archers", "Ice Spirit", "Skeletons", "Rocket", "The Log", "Tornado"),
        "Мортира и быстрый цикл",
    ),
    MetaDeck(
        "miner-poison",
        "Шахтёр + яд",
        "control",
        ("Miner", "Poison", "Knight", "Inferno Dragon", "Bats", "Skeletons", "Rocket", "The Log"),
        "Контроль с шахтёром и ядом",
    ),
    MetaDeck(
        "graveyard",
        "Кладбище + фриз",
        "meta",
        ("Graveyard", "Freeze", "Baby Dragon", "Tornado", "Knight", "Poison", "Ice Wizard", "Barbarian Barrel"),
        "Кладбище с заморозкой",
    ),
    MetaDeck(
        "ebarbs-rg",
        "Элитки + коргиг",
        "meta",
        ("Elite Barbarians", "Royal Giant", "Fireball", "Zap", "Mega Minion", "Electro Spirit", "Skeleton Army", "Cannon"),
        "Агрессивный королевский гигант",
    ),
]

CATEGORY_LABELS = {
    "meta": "Мета",
    "control": "Контроль",
    "beatdown": "Битдаун",
    "cycle": "Цикл",
    "bait": "Бейт",
    "mine": "Мои колоды",
}
