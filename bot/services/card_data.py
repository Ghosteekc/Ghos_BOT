"""Данные о картах: тип, эликсир, счётчики и синергии."""

CARD_META: dict[str, dict] = {
    "Knight": {"elixir": 3, "type": "troop", "role": "tank"},
    "Archers": {"elixir": 3, "type": "troop", "role": "support"},
    "Goblins": {"elixir": 2, "type": "troop", "role": "swarm"},
    "Giant": {"elixir": 5, "type": "troop", "role": "win_condition"},
    "P.E.K.K.A": {"elixir": 7, "type": "troop", "role": "win_condition"},
    "Minions": {"elixir": 3, "type": "troop", "role": "air"},
    "Balloon": {"elixir": 5, "type": "troop", "role": "win_condition"},
    "Witch": {"elixir": 5, "type": "troop", "role": "support"},
    "Barbarians": {"elixir": 5, "type": "troop", "role": "swarm"},
    "Golem": {"elixir": 8, "type": "troop", "role": "win_condition"},
    "Skeletons": {"elixir": 1, "type": "troop", "role": "cycle"},
    "Valkyrie": {"elixir": 4, "type": "troop", "role": "tank"},
    "Skeleton Army": {"elixir": 3, "type": "troop", "role": "swarm"},
    "Bomber": {"elixir": 2, "type": "troop", "role": "splash"},
    "Musketeer": {"elixir": 4, "type": "troop", "role": "support"},
    "Baby Dragon": {"elixir": 4, "type": "troop", "role": "splash"},
    "Prince": {"elixir": 5, "type": "troop", "role": "win_condition"},
    "Wizard": {"elixir": 5, "type": "troop", "role": "splash"},
    "Mini P.E.K.K.A": {"elixir": 4, "type": "troop", "role": "tank"},
    "Spear Goblins": {"elixir": 2, "type": "troop", "role": "swarm"},
    "Giant Skeleton": {"elixir": 6, "type": "troop", "role": "tank"},
    "Hog Rider": {"elixir": 4, "type": "troop", "role": "win_condition"},
    "Minion Horde": {"elixir": 5, "type": "troop", "role": "swarm"},
    "Ice Wizard": {"elixir": 3, "type": "troop", "role": "support"},
    "Royal Giant": {"elixir": 6, "type": "troop", "role": "win_condition"},
    "Guards": {"elixir": 3, "type": "troop", "role": "tank"},
    "Princess": {"elixir": 3, "type": "troop", "role": "support"},
    "Dark Prince": {"elixir": 4, "type": "troop", "role": "tank"},
    "Three Musketeers": {"elixir": 9, "type": "troop", "role": "win_condition"},
    "Lava Hound": {"elixir": 7, "type": "troop", "role": "win_condition"},
    "Ice Spirit": {"elixir": 1, "type": "troop", "role": "cycle"},
    "Fire Spirit": {"elixir": 1, "type": "troop", "role": "cycle"},
    "Miner": {"elixir": 3, "type": "troop", "role": "win_condition"},
    "Sparky": {"elixir": 6, "type": "troop", "role": "win_condition"},
    "Bowler": {"elixir": 5, "type": "troop", "role": "splash"},
    "Lumberjack": {"elixir": 4, "type": "troop", "role": "support"},
    "Battle Ram": {"elixir": 4, "type": "troop", "role": "win_condition"},
    "Inferno Dragon": {"elixir": 4, "type": "troop", "role": "support"},
    "Ice Golem": {"elixir": 2, "type": "troop", "role": "tank"},
    "Mega Minion": {"elixir": 3, "type": "troop", "role": "air"},
    "Dart Goblin": {"elixir": 3, "type": "troop", "role": "support"},
    "Goblin Gang": {"elixir": 3, "type": "troop", "role": "swarm"},
    "Electro Wizard": {"elixir": 4, "type": "troop", "role": "support"},
    "Elite Barbarians": {"elixir": 6, "type": "troop", "role": "win_condition"},
    "Hunter": {"elixir": 4, "type": "troop", "role": "support"},
    "Executioner": {"elixir": 5, "type": "troop", "role": "splash"},
    "Bandit": {"elixir": 3, "type": "troop", "role": "win_condition"},
    "Royal Recruits": {"elixir": 7, "type": "troop", "role": "swarm"},
    "Night Witch": {"elixir": 4, "type": "troop", "role": "support"},
    "Bats": {"elixir": 2, "type": "troop", "role": "swarm"},
    "Royal Ghost": {"elixir": 3, "type": "troop", "role": "win_condition"},
    "Ram Rider": {"elixir": 5, "type": "troop", "role": "win_condition"},
    "Zappies": {"elixir": 4, "type": "troop", "role": "support"},
    "Rascals": {"elixir": 5, "type": "troop", "role": "support"},
    "Cannon Cart": {"elixir": 5, "type": "troop", "role": "support"},
    "Mega Knight": {"elixir": 7, "type": "troop", "role": "tank"},
    "Skeleton Barrel": {"elixir": 3, "type": "troop", "role": "win_condition"},
    "Flying Machine": {"elixir": 4, "type": "troop", "role": "air"},
    "Wall Breakers": {"elixir": 2, "type": "troop", "role": "win_condition"},
    "Royal Hogs": {"elixir": 5, "type": "troop", "role": "win_condition"},
    "Goblin Giant": {"elixir": 6, "type": "troop", "role": "win_condition"},
    "Fisherman": {"elixir": 3, "type": "troop", "role": "support"},
    "Magic Archer": {"elixir": 4, "type": "troop", "role": "support"},
    "Electro Dragon": {"elixir": 5, "type": "troop", "role": "splash"},
    "Firecracker": {"elixir": 3, "type": "troop", "role": "support"},
    "Mighty Miner": {"elixir": 4, "type": "troop", "role": "win_condition"},
    "Elixir Golem": {"elixir": 3, "type": "troop", "role": "win_condition"},
    "Battle Healer": {"elixir": 4, "type": "troop", "role": "support"},
    "Skeleton King": {"elixir": 4, "type": "troop", "role": "win_condition"},
    "Archer Queen": {"elixir": 5, "type": "troop", "role": "win_condition"},
    "Golden Knight": {"elixir": 4, "type": "troop", "role": "win_condition"},
    "Monk": {"elixir": 5, "type": "troop", "role": "support"},
    "Skeleton Dragons": {"elixir": 4, "type": "troop", "role": "air"},
    "Mother Witch": {"elixir": 4, "type": "troop", "role": "support"},
    "Electro Spirit": {"elixir": 1, "type": "troop", "role": "cycle"},
    "Electro Giant": {"elixir": 7, "type": "troop", "role": "win_condition"},
    "Phoenix": {"elixir": 4, "type": "troop", "role": "support"},
    "Little Prince": {"elixir": 3, "type": "troop", "role": "support"},
    "Zap": {"elixir": 2, "type": "spell", "role": "spell"},
    "Arrows": {"elixir": 3, "type": "spell", "role": "spell"},
    "Fireball": {"elixir": 4, "type": "spell", "role": "spell"},
    "Rocket": {"elixir": 6, "type": "spell", "role": "spell"},
    "Goblin Barrel": {"elixir": 3, "type": "spell", "role": "win_condition"},
    "Freeze": {"elixir": 4, "type": "spell", "role": "spell"},
    "Mirror": {"elixir": 1, "type": "spell", "role": "spell"},
    "Lightning": {"elixir": 6, "type": "spell", "role": "spell"},
    "Poison": {"elixir": 4, "type": "spell", "role": "spell"},
    "Graveyard": {"elixir": 5, "type": "spell", "role": "win_condition"},
    "The Log": {"elixir": 2, "type": "spell", "role": "spell"},
    "Tornado": {"elixir": 3, "type": "spell", "role": "spell"},
    "Clone": {"elixir": 3, "type": "spell", "role": "spell"},
    "Earthquake": {"elixir": 3, "type": "spell", "role": "spell"},
    "Barbarian Barrel": {"elixir": 2, "type": "spell", "role": "spell"},
    "Heal Spirit": {"elixir": 1, "type": "spell", "role": "cycle"},
    "Giant Snowball": {"elixir": 2, "type": "spell", "role": "spell"},
    "Royal Delivery": {"elixir": 3, "type": "spell", "role": "spell"},
    "Cannon": {"elixir": 3, "type": "building", "role": "building"},
    "Goblin Hut": {"elixir": 5, "type": "building", "role": "building"},
    "Mortar": {"elixir": 4, "type": "building", "role": "win_condition"},
    "Inferno Tower": {"elixir": 5, "type": "building", "role": "building"},
    "Bomb Tower": {"elixir": 4, "type": "building", "role": "building"},
    "Barbarian Hut": {"elixir": 7, "type": "building", "role": "building"},
    "Tesla": {"elixir": 4, "type": "building", "role": "building"},
    "Elixir Collector": {"elixir": 6, "type": "building", "role": "building"},
    "X-Bow": {"elixir": 6, "type": "building", "role": "win_condition"},
    "Tombstone": {"elixir": 3, "type": "building", "role": "building"},
    "Furnace": {"elixir": 4, "type": "troop", "role": "support"},
    "Goblin Cage": {"elixir": 4, "type": "building", "role": "building"},
    "Goblin Drill": {"elixir": 4, "type": "building", "role": "win_condition"},
    "Goblin Demolisher": {"elixir": 4, "type": "troop", "role": "splash"},
    "Goblin Machine": {"elixir": 5, "type": "troop", "role": "win_condition"},
    "Goblinstein": {"elixir": 5, "type": "troop", "role": "tank"},
    "Goblin Curse": {"elixir": 2, "type": "spell", "role": "spell"},
    "Berserker": {"elixir": 2, "type": "troop", "role": "support"},
    "Boss Bandit": {"elixir": 6, "type": "troop", "role": "win_condition"},
    "Rune Giant": {"elixir": 4, "type": "troop", "role": "win_condition"},
    "Spirit Empress": {"elixir": 6, "type": "troop", "role": "support"},
    "Ronin": {"elixir": 5, "type": "troop", "role": "tank"},
    "Suspicious Bush": {"elixir": 2, "type": "troop", "role": "support"},
    "Vines": {"elixir": 3, "type": "spell", "role": "spell"},
    "Void": {"elixir": 3, "type": "spell", "role": "spell"},
    "Rage": {"elixir": 2, "type": "spell", "role": "spell"},
}

COUNTERS: dict[str, list[str]] = {
    "Hog Rider": [
        "Cannon", "Tesla", "Tornado", "Tombstone", "Bowler", "Barbarians",
        "P.E.K.K.A", "Mini P.E.K.K.A", "Electro Wizard", "Hunter", "Fisherman",
        "Guards", "Skeleton Army", "Ice Golem",
    ],
    "Balloon": ["Inferno Tower", "Musketeer", "Wizard", "Mega Minion", "Inferno Dragon"],
    "Golem": ["Inferno Tower", "Inferno Dragon", "P.E.K.K.A", "Mini P.E.K.K.A"],
    "Graveyard": ["Poison", "Valkyrie", "Wizard", "Baby Dragon", "Bowler"],
    "X-Bow": ["Royal Giant", "Giant", "Earthquake", "Rocket", "Miner"],
    "Mortar": ["Royal Giant", "Giant", "Earthquake", "Miner", "Hog Rider"],
    "Royal Giant": ["Inferno Tower", "P.E.K.K.A", "Mini P.E.K.K.A", "Inferno Dragon"],
    "Goblin Barrel": ["The Log", "Arrows", "Barbarian Barrel", "Giant Snowball", "Princess"],
    "Lava Hound": ["Inferno Tower", "Inferno Dragon", "Mega Minion", "Musketeer"],
    "Miner": ["Knight", "Valkyrie", "Skeleton Army", "Guards", "Cannon"],
    "Mega Knight": ["Inferno Tower", "P.E.K.K.A", "Mini P.E.K.K.A", "Inferno Dragon", "Knight", "Ronin"],
    "Electro Giant": ["Inferno Tower", "Inferno Dragon", "P.E.K.K.A", "Mini P.E.K.K.A"],
    "Wall Breakers": ["The Log", "Barbarian Barrel", "Skeleton Army", "Goblin Gang"],
    "Battle Ram": ["Cannon", "Tesla", "Tornado", "Skeleton Army"],
    "Skeleton Barrel": ["Arrows", "Zap", "The Log", "Princess", "Musketeer"],
    "Elite Barbarians": ["Skeleton Army", "Valkyrie", "Mini P.E.K.K.A", "Knight"],
    "Three Musketeers": ["Fireball", "Lightning", "Rocket", "Valkyrie"],
    "Sparky": ["Zap", "Rocket", "Lightning", "Goblin Barrel", "Miner"],
    "Giant": ["Inferno Tower", "Inferno Dragon", "Mini P.E.K.K.A", "P.E.K.K.A"],
    "P.E.K.K.A": ["Skeleton Army", "Guards", "Goblin Gang", "Inferno Tower", "Ronin"],
    "Royal Ghost": ["Valkyrie", "Knight", "Barbarians", "Mega Minion", "Poison"],
    "Bandit": [
        "Valkyrie", "Ronin", "Guards", "Knight", "Barbarians",
        "Skeleton Army", "Goblin Gang", "Tesla", "P.E.K.K.A", "Mini P.E.K.K.A",
        "Mega Minion", "Hunter",
    ],
    "Ram Rider": ["Cannon", "Tesla", "Skeleton Army", "P.E.K.K.A"],
    "Prince": ["Skeleton Army", "Goblin Gang", "Tombstone", "Barbarians", "Ronin"],
    "Rune Giant": ["Inferno Tower", "Inferno Dragon", "Mini P.E.K.K.A", "Cannon"],
    "Boss Bandit": ["Inferno Tower", "P.E.K.K.A", "Skeleton Army", "Knight", "Ronin"],
    "Ronin": ["Skeleton Army", "Goblin Gang", "Minions", "Musketeer", "Wizard", "Mega Minion"],
    "Witch": ["Valkyrie", "Knight", "Prince", "Mini P.E.K.K.A", "Baby Dragon", "Poison", "Fireball"],
    "Mother Witch": ["Valkyrie", "Fireball", "Poison", "Wizard", "Mega Minion"],
    "Firecracker": ["The Log", "Arrows", "Fireball", "Zap", "Barbarian Barrel"],
    "Ice Spirit": ["The Log", "Zap", "Giant Snowball", "Barbarian Barrel"],
    "Goblins": ["The Log", "Zap", "Arrows", "Barbarian Barrel", "Wizard", "Valkyrie"],
    "Skeletons": ["The Log", "Zap", "Barbarian Barrel", "Giant Snowball", "Arrows"],
    "Cannon": ["Hog Rider", "Battle Ram", "Giant", "Goblin Drill"],
    "Tesla": ["Hog Rider", "Battle Ram", "Balloon", "Lava Hound", "Miner"],
    "Golden Knight": ["Skeleton Army", "Guards", "Mini P.E.K.K.A", "P.E.K.K.A", "Inferno Tower"],
    "Archer Queen": ["Fireball", "Lightning", "Rocket", "Mini P.E.K.K.A", "Skeleton Army"],
    "Skeleton King": ["Mini P.E.K.K.A", "Inferno Tower", "P.E.K.K.A", "Poison"],
    "Mighty Miner": ["Tesla", "Cannon", "Skeleton Army", "Knight"],
    "Monk": ["Skeleton Army", "Mini P.E.K.K.A", "Inferno Tower", "Knight"],
    "Little Prince": ["Fireball", "Arrows", "The Log", "Mega Minion"],
    "Phoenix": ["Inferno Tower", "Inferno Dragon", "Mega Minion", "Musketeer"],
    "Electro Wizard": ["Sparky", "Elite Barbarians", "Barbarians"],
    "Tornado": ["Balloon", "Lava Hound", "Miner", "Goblin Barrel"],
}

SYNERGIES: dict[str, list[str]] = {
    "Hog Rider": ["Ice Golem", "Ice Spirit", "Skeletons", "Musketeer", "Cannon", "Fireball"],
    "Balloon": ["Lumberjack", "Freeze", "Baby Dragon", "Tornado", "Miner"],
    "Golem": ["Night Witch", "Baby Dragon", "Lightning", "Tornado", "Elixir Collector"],
    "Graveyard": ["Freeze", "Poison", "Knight", "Ice Wizard", "Baby Dragon"],
    "Lava Hound": ["Balloon", "Mega Minion", "Tombstone", "Lightning", "Arrows"],
    "X-Bow": ["Tesla", "Archers", "Knight", "Ice Spirit", "Skeletons"],
    "Mortar": ["Knight", "Archers", "Skeletons", "Ice Spirit", "Rocket"],
    "Royal Giant": ["Fisherman", "Hunter", "Lightning", "Fireball", "Electro Spirit"],
    "Goblin Barrel": ["Princess", "Goblin Gang", "Knight", "Inferno Tower", "Rocket"],
    "Miner": ["Poison", "Wall Breakers", "Bats", "Skeleton Army", "Goblin Gang"],
    "Mega Knight": ["Inferno Dragon", "Bats", "Zap", "Miner", "Poison"],
    "Electro Giant": ["Tornado", "Lightning", "Golden Knight", "Battle Healer"],
    "Hunter": ["Royal Giant", "Giant", "Elixir Golem", "Freeze"],
    "Giant": ["Musketeer", "Wizard", "Mini P.E.K.K.A", "Arrows", "Zap"],
    "P.E.K.K.A": ["Battle Ram", "Poison", "Electro Wizard", "Zap", "Bandit"],
    "Wall Breakers": ["Miner", "Goblin Gang", "Fire Spirit", "Bats", "Skeleton Army"],
    "Battle Ram": ["Bandit", "Dark Prince", "Royal Ghost", "Zap", "Fireball"],
    "Skeleton King": ["Graveyard", "Giant Skeleton", "Tornado", "Arrows"],
    "Archer Queen": ["P.E.K.K.A", "Giant", "Royal Giant", "Skeleton Army"],
}

ARENA_CARD_POOL: dict[str, list[str]] = {
    "low": ["Knight", "Archers", "Goblins", "Giant", "Minions", "Arrows", "Fireball",
            "Zap", "Cannon", "Skeletons", "Musketeer", "Mini P.E.K.K.A", "Hog Rider",
            "Valkyrie", "Bomber", "Barbarians", "Ice Spirit", "Fire Spirit"],
    "mid": ["Balloon", "Witch", "Prince", "Wizard", "Goblin Barrel", "Inferno Tower",
            "Baby Dragon", "Skeleton Army", "Tesla", "Mortar", "Tornado", "The Log",
            "Ice Golem", "Mega Minion", "Dart Goblin", "Goblin Gang", "Battle Ram",
            "Poison", "Furnace", "Graveyard", "Freeze"],
    "high": ["Lava Hound", "Graveyard", "Sparky", "Miner", "Bandit", "Night Witch",
             "Royal Ghost", "Magic Archer", "Electro Wizard", "Mega Knight",
             "Wall Breakers", "Elixir Golem", "Skeleton King", "Phoenix", "Ronin"],
}

WIN_CONDITIONS = {
    "Hog Rider", "Balloon", "Golem", "Graveyard", "X-Bow", "Mortar", "Royal Giant",
    "Goblin Barrel", "Lava Hound", "Miner", "Giant", "P.E.K.K.A", "Battle Ram",
    "Wall Breakers", "Royal Hogs", "Goblin Giant", "Elixir Giant", "Electro Giant",
    "Skeleton Barrel", "Sparky", "Three Musketeers", "Elite Barbarians", "Goblin Drill",
}

# Спам-толпы (не путать со Стражами — те танкуют точечный урон)
SWARM_CARDS = {
    "Goblins", "Spear Goblins", "Skeleton Army", "Goblin Gang", "Barbarians",
    "Minion Horde", "Bats", "Skeletons", "Royal Recruits",
}

# Сильные юниты с точечным уроном (не сплеш) — Стражи и подобные карты их держат
POINT_TARGET_THREATS = {
    "P.E.K.K.A", "Mini P.E.K.K.A", "Prince", "Hog Rider", "Bandit", "Sparky",
    "Inferno Dragon", "Lumberjack", "Golden Knight", "Mighty Miner", "Monk",
    "Mega Knight", "Dark Prince", "Elite Barbarians", "Boss Bandit", "Rune Giant",
}

POINT_TARGET_COUNTERS = {"Guards", "Knight", "Ice Golem", "Skeleton Army", "Ronin"}

# На заклинания нет карты-контры, кроме Монаха — отражает Фаербол и Ракету
SPELL_CARD_COUNTERS: dict[str, list[str]] = {
    "Fireball": ["Monk"],
    "Rocket": ["Monk"],
}


def get_card_elixir(name: str) -> int:
    return CARD_META.get(name, {}).get("elixir", 4)


def get_card_role(name: str) -> str:
    return CARD_META.get(name, {}).get("role", "support")


def is_spam_card(name: str) -> bool:
    return name in SWARM_CARDS or get_card_role(name) == "swarm"


def is_point_target_threat(name: str) -> bool:
    return name in POINT_TARGET_THREATS


def has_point_target_answer(cards: list[str]) -> bool:
    return bool(set(cards) & POINT_TARGET_COUNTERS)


def is_pure_spell(name: str) -> bool:
    """Заклинание без win-condition — карта-контра на него не ставится."""
    meta = CARD_META.get(name, {})
    if meta.get("type") != "spell":
        return False
    return get_card_role(name) != "win_condition"


def card_counters_for_spell(spell: str) -> list[str]:
    """Карты, которые контрят заклинание (единственное исключение — Монах)."""
    return list(SPELL_CARD_COUNTERS.get(spell, []))
