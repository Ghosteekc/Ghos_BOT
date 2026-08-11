"""Константы интеллектуального генератора колод."""

from __future__ import annotations

# Роли (теги в cards.json)
ROLE_WIN = "win_condition"
ROLE_TANK = "tank"
ROLE_MINI_TANK = "mini_tank"
ROLE_SPLASH = "splash"
ROLE_SMALL_SPELL = "small_spell"
ROLE_BIG_SPELL = "big_spell"
ROLE_BUILDING = "building"
ROLE_AIR = "air_defense"  # legacy name: anti-air capability, NOT is_flying
ROLE_AIR_DEFENSE = ROLE_AIR
ROLE_FLYING = "flying"
ROLE_SWARM = "swarm"
ROLE_CYCLE = "cycle"
ROLE_ANTI_TANK = "anti_tank"
ROLE_DEFENSIVE = "defensive"
ROLE_ANTI_SWARM = "anti_swarm"
ROLE_COUNTERPUSH = "counterpush"
ROLE_DPS = "dps"
ROLE_SUPPORT = "support"

ARCHETYPES = (
    "Log Bait",
    "Cycle",
    "Beatdown",
    "Control",
    "Bridge Spam",
    "Lava",
    "Royal Giant",
    "Graveyard",
    "Siege",
    "Fireball Bait",
    "Split Lane",
    "Meta",
)

# Веса рейтинга похожести колод (шаг 3)
WEIGHT_CARD_MATCH = 25.0      # за каждую совпавшую карту ядра
WEIGHT_ARCHETYPE = 20.0
WEIGHT_ELIXIR = 15.0
WEIGHT_SYNERGY = 15.0
WEIGHT_POPULARITY = 5.0

# Диапазон среднего эликсира
DEFAULT_ELIXIR_MIN = 2.6
DEFAULT_ELIXIR_MAX = 4.6

ARCHETYPE_ELIXIR: dict[str, tuple[float, float]] = {
    "Cycle": (2.6, 3.4),
    "Log Bait": (2.8, 3.6),
    "Beatdown": (3.8, 4.6),
    "Lava": (3.5, 4.4),
    "Royal Giant": (3.4, 4.2),
    "Bridge Spam": (3.6, 4.4),
    "Siege": (2.8, 3.6),
    "Control": (3.0, 4.0),
    "Graveyard": (3.2, 4.2),
    "Split Lane": (2.8, 3.6),
    "Fireball Bait": (2.8, 3.8),
    "Meta": (2.8, 4.4),
}

# Карты-якоря архетипов
ARCHETYPE_ANCHORS: dict[str, set[str]] = {
    "Log Bait": {"Goblin Barrel", "Princess", "Goblin Gang"},
    "Cycle": {"Hog Rider", "Ice Golem", "Skeletons", "Ice Spirit"},
    "Beatdown": {"Golem", "Giant", "P.E.K.K.A", "Electro Giant"},
    "Lava": {"Lava Hound", "Balloon"},
    "Royal Giant": {"Royal Giant", "Fisherman", "Hunter"},
    "Bridge Spam": {"P.E.K.K.A", "Battle Ram", "Bandit", "Royal Ghost"},
    "Siege": {"X-Bow", "Mortar"},
    "Control": {"Miner", "Poison", "Tornado", "Inferno Tower"},
    "Graveyard": {"Graveyard", "Freeze"},
    "Fireball Bait": {"Goblin Barrel", "Princess", "Fireball"},
    "Split Lane": {"Royal Hogs", "Wall Breakers", "Miner"},
}

# Известные пары синергии (базовые коэффициенты)
KNOWN_SYNERGY_PAIRS: dict[frozenset[str], int] = {
    frozenset({"Knight", "Goblin Barrel"}): 96,
    frozenset({"Princess", "Goblin Barrel"}): 99,
    frozenset({"Goblin Barrel", "Goblin Gang"}): 90,
    frozenset({"Rocket", "Inferno Tower"}): 88,
    frozenset({"Hog Rider", "Ice Golem"}): 94,
    frozenset({"Hog Rider", "Earthquake"}): 93,
    frozenset({"Hog Rider", "Fireball"}): 88,
    frozenset({"Hog Rider", "The Log"}): 86,
    frozenset({"Lava Hound", "Balloon"}): 97,
    frozenset({"Lumberjack", "Balloon"}): 96,
    frozenset({"Balloon", "Freeze"}): 90,
    frozenset({"Golem", "Night Witch"}): 95,
    frozenset({"Golem", "Baby Dragon"}): 90,
    frozenset({"Golem", "Lightning"}): 88,
    frozenset({"Miner", "Poison"}): 92,
    frozenset({"Graveyard", "Poison"}): 94,
    frozenset({"Graveyard", "Freeze"}): 91,
    frozenset({"Royal Giant", "Fisherman"}): 91,
    frozenset({"Royal Hogs", "Earthquake"}): 89,
    frozenset({"Mega Knight", "Inferno Dragon"}): 90,
    frozenset({"Ice Spirit", "Musketeer"}): 85,
    frozenset({"Tornado", "Executioner"}): 96,
    frozenset({"Tornado", "Magic Archer"}): 96,
    frozenset({"Tornado", "Bowler"}): 95,
    frozenset({"Tornado", "Ice Wizard"}): 94,
    frozenset({"X-Bow", "Tesla"}): 93,
    frozenset({"Mortar", "Knight"}): 88,
    frozenset({"Battle Ram", "P.E.K.K.A"}): 92,
    frozenset({"Bandit", "Royal Ghost"}): 90,
    frozenset({"Sparky", "Giant"}): 87,
    frozenset({"Three Musketeers", "Elixir Collector"}): 90,
}

SYNERGY_STRONG = 88
SYNERGY_PARTIAL = 72
SYNERGY_WEAK = 55

GENERIC_CARDS = frozenset({
    "The Log", "Zap", "Arrows", "Fireball", "Knight", "Skeletons", "Ice Spirit",
    "Electro Spirit", "Fire Spirit", "Heal Spirit", "Bats", "Goblins", "Spear Goblins",
    "Cannon", "Tesla", "Musketeer", "Ice Golem", "Giant Snowball", "Barbarian Barrel",
})

MAX_SPELLS = 3
MAX_WINS = 1

ARCHETYPE_PRIMARY_WIN: dict[str, list[str]] = {
    "Cycle": ["Hog Rider", "Mortar", "Miner", "Wall Breakers"],
    "Log Bait": ["Goblin Barrel"],
    "Beatdown": ["Golem", "Giant", "Electro Giant", "P.E.K.K.A", "Goblin Giant"],
    "Lava": ["Lava Hound", "Balloon"],
    "Royal Giant": ["Royal Giant"],
    "Bridge Spam": ["Battle Ram", "Ram Rider", "P.E.K.K.A", "Elite Barbarians"],
    "Siege": ["X-Bow", "Mortar"],
    "Control": ["Miner", "X-Bow", "Graveyard", "Goblin Drill"],
    "Graveyard": ["Graveyard"],
    "Meta": ["Hog Rider", "Miner", "Battle Ram", "Royal Giant", "Goblin Barrel"],
}
