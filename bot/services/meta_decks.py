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
        "Hog 2.6",
        "cycle",
        ("Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"),
        "Классический цикл с Hog Rider",
    ),
    MetaDeck(
        "log-bait",
        "Log Bait",
        "bait",
        ("Goblin Barrel", "Princess", "Goblin Gang", "Ice Spirit", "Knight", "Inferno Tower", "Rocket", "The Log"),
        "Провокация заклинаний + Goblin Barrel",
    ),
    MetaDeck(
        "xbow-30",
        "X-Bow 3.0",
        "control",
        ("X-Bow", "Tesla", "Archers", "Ice Spirit", "Skeletons", "Fireball", "The Log", "Knight"),
        "Контроль с X-Bow и Tesla",
    ),
    MetaDeck(
        "giant-dprince",
        "Giant Double Prince",
        "beatdown",
        ("Giant", "Dark Prince", "Prince", "Miner", "Musketeer", "Electro Wizard", "Poison", "Zap"),
        "Битдаун с двойным Prince",
    ),
    MetaDeck(
        "rg-fish",
        "Royal Giant Fisherman",
        "meta",
        ("Royal Giant", "Fisherman", "Hunter", "Fireball", "Lightning", "Electro Spirit", "Skeletons", "Cannon"),
        "Royal Giant + Fisherman",
    ),
    MetaDeck(
        "pekka-bs",
        "P.E.K.K.A Bridge Spam",
        "meta",
        ("P.E.K.K.A", "Battle Ram", "Bandit", "Royal Ghost", "Magic Archer", "Electro Wizard", "Poison", "Zap"),
        "Bridge spam вокруг P.E.K.K.A",
    ),
    MetaDeck(
        "lava-loon",
        "LavaLoon",
        "beatdown",
        ("Lava Hound", "Balloon", "Mega Minion", "Tombstone", "Guards", "Arrows", "Lightning", "Barbarian Barrel"),
        "Воздушный битдаун",
    ),
    MetaDeck(
        "golem-nw",
        "Golem Night Witch",
        "beatdown",
        ("Golem", "Night Witch", "Baby Dragon", "Mega Minion", "Lumberjack", "Tornado", "Lightning", "Barbarian Barrel"),
        "Классический Golem push",
    ),
    MetaDeck(
        "mortar-cycle",
        "Mortar Cycle",
        "cycle",
        ("Mortar", "Knight", "Archers", "Ice Spirit", "Skeletons", "Rocket", "The Log", "Tornado"),
        "Mortar + cycle",
    ),
    MetaDeck(
        "miner-poison",
        "Miner Poison",
        "control",
        ("Miner", "Poison", "Knight", "Inferno Dragon", "Bats", "Skeletons", "Rocket", "The Log"),
        "Контроль с Miner и Poison",
    ),
    MetaDeck(
        "graveyard",
        "Graveyard Freeze",
        "meta",
        ("Graveyard", "Freeze", "Baby Dragon", "Tornado", "Knight", "Poison", "Ice Wizard", "Barbarian Barrel"),
        "Graveyard + Freeze",
    ),
    MetaDeck(
        "ebarbs-rg",
        "Elite Barbarians Cycle",
        "meta",
        ("Elite Barbarians", "Royal Giant", "Fireball", "Zap", "Mega Minion", "Electro Spirit", "Skeleton Army", "Cannon"),
        "Агрессивный Royal Giant",
    ),
]

CATEGORY_LABELS = {
    "meta": "Мета",
    "control": "Контроль",
    "beatdown": "Битдаун",
    "cycle": "Цикл",
    "bait": "Bait",
    "mine": "Мои колоды",
}
