"""Генерация bot/data/cards.json и bot/data/decks.json для deck builder."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.services.card_data import CARD_META, WIN_CONDITIONS, get_card_elixir  # noqa: E402
from bot.services.meta_decks import META_DECKS  # noqa: E402

DATA_DIR = ROOT / "bot" / "data"
WEBAPP_DATA = ROOT.parent / "webapp" / "src" / "data"

MINI_TANKS = {
    "Knight", "Ice Golem", "Guards", "Dark Prince", "Valkyrie", "Mini P.E.K.K.A",
    "Bandit", "Lumberjack", "Battle Healer",
}
TANKS = {
    "Giant", "Golem", "P.E.K.K.A", "Mega Knight", "Giant Skeleton", "Electro Giant",
    "Goblin Giant", "Royal Giant", "Elixir Golem", "Sparky", "Lava Hound", "Ronin",
    "Goblinstein", "Boss Bandit",
}
SMALL_SPELLS = {
    "Zap", "The Log", "Giant Snowball", "Barbarian Barrel", "Arrows", "Rage",
}
BIG_SPELLS = {
    "Fireball", "Rocket", "Lightning", "Poison", "Freeze", "Earthquake",
}
AIR_DEFENSE = {
    "Musketeer", "Mega Minion", "Wizard", "Archers", "Inferno Dragon", "Electro Wizard",
    "Hunter", "Magic Archer", "Flying Machine", "Minions", "Bats", "Skeleton Dragons",
    "Ice Wizard", "Princess", "Firecracker", "Mother Witch", "Phoenix",
}
ANTI_TANK = {
    "Inferno Tower", "Inferno Dragon", "P.E.K.K.A", "Mini P.E.K.K.A", "Hunter",
    "Guards", "Knight", "Cannon", "Tesla", "Tombstone",
}
DEFENSIVE = {
    "Knight", "Valkyrie", "Guards", "Ice Golem", "Cannon", "Tesla", "Tombstone",
    "Inferno Tower", "Bomb Tower", "Inferno Dragon", "Mega Knight",
}
ANTI_SWARM = {
    "Valkyrie", "Wizard", "Baby Dragon", "Executioner", "Bowler", "Bomber",
    "The Log", "Zap", "Arrows", "Barbarian Barrel", "Giant Snowball", "Fireball",
    "Poison", "Tornado", "Earthquake",
}
COUNTERPUSH = {
    "Bandit", "Dark Prince", "Prince", "Battle Ram", "Royal Ghost", "Miner",
    "Hog Rider", "Wall Breakers", "Ram Rider", "Elite Barbarians",
}
DPS = {
    "Musketeer", "Wizard", "Electro Wizard", "Hunter", "Magic Archer", "Mini P.E.K.K.A",
    "Inferno Dragon", "Lumberjack", "Prince", "Dark Prince", "Bandit",
}

ARCHETYPE_MAP = {
    "cycle": "Cycle",
    "bait": "Log Bait",
    "control": "Control",
    "beatdown": "Beatdown",
    "meta": "Meta",
}

ARCHETYPE_ALIASES = {
    "hog-26": "Cycle",
    "log-bait": "Log Bait",
    "xbow-30": "Siege",
    "giant-dprince": "Beatdown",
    "rg-fish": "Royal Giant",
    "pekka-bs": "Bridge Spam",
    "lava-loon": "Lava",
    "golem-nw": "Beatdown",
    "mortar-cycle": "Siege",
    "miner-poison": "Control",
    "graveyard": "Graveyard",
    "ebarbs-rg": "Royal Giant",
}


def _roles_for(name: str, meta: dict) -> list[str]:
    roles: list[str] = []
    base = meta.get("role", "support")
    ctype = meta.get("type", "troop")
    elixir = int(meta.get("elixir", 4))

    if name in WIN_CONDITIONS or base == "win_condition":
        roles.append("win_condition")
    if name in TANKS:
        roles.append("tank")
    if name in MINI_TANKS:
        roles.append("mini_tank")
    if base == "splash" or name in {"Baby Dragon", "Wizard", "Executioner", "Bowler", "Valkyrie"}:
        roles.append("splash")
    if ctype == "spell":
        roles.append("spell")
        if name in SMALL_SPELLS or elixir <= 2:
            roles.append("small_spell")
        if name in BIG_SPELLS or elixir >= 4:
            roles.append("big_spell")
    if ctype == "building" or base == "building":
        roles.append("building")
    if name in AIR_DEFENSE or base == "air":
        roles.append("air_defense")
    if base == "swarm" or name in {"Goblins", "Skeleton Army", "Goblin Gang", "Barbarians"}:
        roles.append("swarm")
    if base == "cycle" or name in {"Skeletons", "Ice Spirit", "Electro Spirit", "Fire Spirit", "Heal Spirit", "Bats"}:
        roles.append("cycle")
    if name in ANTI_TANK:
        roles.append("anti_tank")
    if name in DEFENSIVE:
        roles.append("defensive")
    if name in ANTI_SWARM:
        roles.append("anti_swarm")
    if name in COUNTERPUSH:
        roles.append("counterpush")
    if name in DPS or base == "support":
        roles.append("support")
        if name in DPS:
            roles.append("dps")

    if not roles:
        roles.append("support")
    return sorted(set(roles))


def build_cards_json() -> dict:
    cards = {}
    for name, meta in sorted(CARD_META.items()):
        cards[name] = {
            "elixir": int(meta.get("elixir", 4)),
            "type": meta.get("type", "troop"),
            "roles": _roles_for(name, meta),
        }
    return {"cards": cards, "version": 1}


def _deck_archetype(meta_deck) -> str:
    return ARCHETYPE_ALIASES.get(meta_deck.key, ARCHETYPE_MAP.get(meta_deck.category, "Meta"))


def build_decks_json() -> dict:
    decks = []
    pair_counts: dict[str, int] = {}

    for i, md in enumerate(META_DECKS):
        cards = list(md.cards)
        avg = round(sum(get_card_elixir(c) for c in cards) / 8, 2)
        decks.append({
            "id": f"meta-{md.key}",
            "name": md.name,
            "archetype": _deck_archetype(md),
            "avgElixir": avg,
            "cards": cards,
            "source": "curated",
            "popularity": 100 - i,
        })
        for a in cards:
            for b in cards:
                if a >= b:
                    continue
                key = f"{a}|{b}"
                pair_counts[key] = pair_counts.get(key, 0) + 1

    synergy_pairs: dict[str, int] = {}
    for key, count in pair_counts.items():
        a, b = key.split("|")
        score = min(99, 72 + count * 8)
        synergy_pairs[key] = score
        synergy_pairs[f"{b}|{a}"] = score

    return {
        "decks": decks,
        "synergyPairs": synergy_pairs,
        "meta": {"version": 1, "count": len(decks), "source": "meta_decks"},
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {path} ({path.stat().st_size} bytes)")


def main() -> None:
    cards = build_cards_json()
    decks = build_decks_json()
    write_json(DATA_DIR / "cards.json", cards)
    write_json(DATA_DIR / "decks.json", decks)
    if WEBAPP_DATA.parent.exists():
        write_json(WEBAPP_DATA / "cards.json", cards)
        write_json(WEBAPP_DATA / "decks.json", decks)
    else:
        print(f"Skip webapp sync: {WEBAPP_DATA.parent} not found")


if __name__ == "__main__":
    main()
