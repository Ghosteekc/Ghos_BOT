"""Константы интеллектуального генератора колод."""

from __future__ import annotations

# Роли (теги в cards.json)
ROLE_WIN = "win_condition"
ROLE_TANK = "tank"
ROLE_MINI_TANK = "mini_tank"
ROLE_SPLASH = "splash"
ROLE_SPELL = "spell"
ROLE_SMALL_SPELL = "small_spell"
ROLE_BIG_SPELL = "big_spell"
ROLE_BUILDING = "building"
ROLE_AIR = "air_defense"
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

MATCH_CONFIDENCE_THRESHOLD = 80.0
SYNERGY_MIN_THRESHOLD = 80.0

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
    "Meta": (2.8, 4.4),
}

# Приоритет добора (legacy; в finalize используется scoring, не жёсткий цикл).
FILL_PRIORITY: list[str] = [
    ROLE_WIN,
    ROLE_BIG_SPELL,
    ROLE_SMALL_SPELL,
    ROLE_AIR,
    ROLE_MINI_TANK,
    ROLE_BUILDING,
    ROLE_DPS,
    ROLE_CYCLE,
    ROLE_COUNTERPUSH,
]

# Карты-якоря архетипов
ARCHETYPE_ANCHORS: dict[str, set[str]] = {
    "Log Bait": {"Goblin Barrel", "Princess", "Goblin Gang"},
    "Cycle": {"Hog Rider", "Ice Golem", "Skeletons", "Ice Spirit"},
    "Beatdown": {"Golem", "Giant", "P.E.K.K.A", "Electro Giant"},
    "Lava": {"Lava Hound", "Balloon"},
    "Royal Giant": {"Royal Giant", "Fisherman", "Hunter"},
    "Bridge Spam": {"P.E.K.K.A", "Battle Ram", "Bandit", "Royal Ghost"},
    "Siege": {"X-Bow", "Mortar", "Tesla"},
    "Control": {"Miner", "X-Bow", "Tesla"},
    "Graveyard": {"Graveyard", "Freeze"},
    "Fireball Bait": {"Goblin Barrel", "Princess", "Fireball"},
    "Split Lane": {"Royal Hogs", "Wall Breakers", "Miner"},
}

# Известные пары синергии (базовые коэффициенты)
KNOWN_SYNERGY_PAIRS: dict[frozenset[str], int] = {
    frozenset({"Knight", "Goblin Barrel"}): 96,
    frozenset({"Princess", "Goblin Barrel"}): 99,
    frozenset({"Rocket", "Inferno Tower"}): 88,
    frozenset({"Hog Rider", "Ice Golem"}): 94,
    frozenset({"Lava Hound", "Balloon"}): 97,
    frozenset({"Golem", "Night Witch"}): 95,
    frozenset({"Miner", "Poison"}): 92,
    frozenset({"Royal Giant", "Fisherman"}): 91,
    frozenset({"Mega Knight", "Inferno Dragon"}): 90,
    frozenset({"Ice Spirit", "Musketeer"}): 85,
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
