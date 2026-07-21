#!/usr/bin/env python3
"""Scrape counter/synergy data from deckshop.pro into bot/data/deckshop_counters.py.

Usage:
    python scripts/scrape_deckshop_counters.py
    python scripts/scrape_deckshop_counters.py --slug hog-rider  # single card test
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "bot" / "data" / "deckshop_counters.py"

BASE_URL = "https://www.deckshop.pro/ru/card/detail/{slug}"
STATS_URL = "https://www.deckshop.pro/ru/card/stats"
USER_AGENT = "GhosteekBot/1.0 (counter research; +https://github.com/Ghosteekc/Ghos_BOT)"

CARD_ANCHOR = re.compile(
    r'href="/ru/card/detail/([a-z0-9-]+)"[^>]*>\s*<div[^>]*class="([^"]*)"[^>]*>\s*<img[^>]*alt="([^"]*)"',
    re.S,
)
SPELL_IMG = re.compile(r'<img src="/img/c/([^"]+\.png)" class="card" alt="([^"]*)">')
CARD_TITLE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
CARD_LIST_BLOCK = re.compile(
    r'<div class="card-list display-elixir"[^>]*id="([^"]*)"[^>]*>(.*?)</div>\s*</div>',
    re.S,
)

# DeckShop slug -> Clash Royale API card name (extend as needed during scrape).
SLUG_OVERRIDES: dict[str, str] = {
    "pekka": "P.E.K.K.A",
    "mini-pekka": "Mini P.E.K.K.A",
    "the-log": "The Log",
    "x-bow": "X-Bow",
    "3m": "Three Musketeers",
    "ebarbs": "Elite Barbarians",
    "ewiz": "Electro Wizard",
    "e-wiz": "Electro Wizard",
    "electro-wizard": "Electro Wizard",
    "mega-knight": "Mega Knight",
    "royal-hogs": "Royal Hogs",
    "goblin-barrel": "Goblin Barrel",
    "goblin-gang": "Goblin Gang",
    "goblin-hut": "Goblin Hut",
    "goblin-cage": "Goblin Cage",
    "goblin-drill": "Goblin Drill",
    "goblin-giant": "Goblin Giant",
    "dark-prince": "Dark Prince",
    "ice-wizard": "Ice Wizard",
    "ice-golem": "Ice Golem",
    "ice-spirit": "Ice Spirit",
    "fire-spirit": "Fire Spirit",
    "electro-spirit": "Electro Spirit",
    "heal-spirit": "Heal Spirit",
    "skeleton-army": "Skeleton Army",
    "skeleton-king": "Skeleton King",
    "skeleton-dragons": "Skeleton Dragons",
    "skeleton-barrel": "Skeleton Barrel",
    "giant-skeleton": "Giant Skeleton",
    "royal-giant": "Royal Giant",
    "royal-recruits": "Royal Recruits",
    "royal-ghost": "Royal Ghost",
    "royal-delivery": "Royal Delivery",
    "baby-dragon": "Baby Dragon",
    "inferno-dragon": "Inferno Dragon",
    "electro-dragon": "Electro Dragon",
    "mega-minion": "Mega Minion",
    "minion-horde": "Minion Horde",
    "dart-goblin": "Dart Goblin",
    "spear-goblins": "Spear Goblins",
    "wall-breakers": "Wall Breakers",
    "battle-ram": "Battle Ram",
    "battle-healer": "Battle Healer",
    "cannon-cart": "Cannon Cart",
    "barbarian-barrel": "Barbarian Barrel",
    "barbarian-hut": "Barbarian Hut",
    "giant-snowball": "Giant Snowball",
    "hog-rider": "Hog Rider",
    "ram-rider": "Ram Rider",
    "magic-archer": "Magic Archer",
    "mother-witch": "Mother Witch",
    "night-witch": "Night Witch",
    "elite-barbarians": "Elite Barbarians",
    "three-musketeers": "Three Musketeers",
    "lava-hound": "Lava Hound",
    "golden-knight": "Golden Knight",
    "archer-queen": "Archer Queen",
    "mighty-miner": "Mighty Miner",
    "little-prince": "Little Prince",
    "boss-bandit": "Boss Bandit",
    "spirit-empress": "Spirit Empress",
    "rune-giant": "Rune Giant",
    "goblin-demolisher": "Goblin Demolisher",
    "goblin-machine": "Goblin Machine",
    "goblinstein": "Goblinstein",
    "elixir-golem": "Elixir Golem",
    "electro-giant": "Electro Giant",
    "flying-machine": "Flying Machine",
    "bomb-tower": "Bomb Tower",
    "inferno-tower": "Inferno Tower",
    "suspicious-bush": "Suspicious Bush",
}


def _compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _slug_to_title(slug: str) -> str:
    if slug in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[slug]
    parts = slug.replace("evo-", "Evo ").replace("hero-", "Hero ").split("-")
    return " ".join(p.capitalize() if p not in {"pekk", "a"} else p.upper() for p in parts)


def _build_name_index() -> dict[str, str]:
    """slug/compact -> API-style English name from CARD_META."""
    try:
        from bot.services.card_data import CARD_META
    except ImportError:
        CARD_META = {}

    index: dict[str, str] = {}
    for name in CARD_META:
        index[_compact(name)] = name
    for slug, name in SLUG_OVERRIDES.items():
        index[_compact(slug)] = name
        index[_compact(name)] = name
    return index


def _resolve_name(slug: str, name_ru: str, index: dict[str, str]) -> str:
    if slug in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[slug]
    hit = index.get(_compact(slug))
    if hit:
        return hit
    # evo-knight -> Knight with Evo prefix handled separately
    if slug.startswith("evo-"):
        base = slug[4:]
        base_name = _resolve_name(base, name_ru, index)
        return f"Evo {base_name}" if not base_name.startswith("Evo ") else base_name
    if slug.startswith("hero-"):
        base = slug[5:]
        base_name = _resolve_name(base, name_ru, index)
        return f"Hero {base_name}" if not base_name.startswith("Hero ") else base_name
    return _slug_to_title(slug)


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


def _parse_card_links(block_html: str, index: dict[str, str]) -> tuple[list[str], list[str]]:
    strong: list[str] = []
    partial: list[str] = []
    for slug, div_cls, _alt in CARD_ANCHOR.findall(block_html):
        name = _resolve_name(slug, _alt, index)
        if "opacity-25" in div_cls or "opacity-50" in div_cls:
            partial.append(name)
        else:
            strong.append(name)
    return strong, partial


def _parse_spells_not_killing(html: str, index: dict[str, str]) -> list[str]:
    idx = html.find("Не убивается")
    if idx < 0:
        return []
    chunk = html[idx : idx + 4000]
    spells: list[str] = []
    for img_file, alt in SPELL_IMG.findall(chunk):
        # map by alt or img filename heuristics
        slug = img_file.replace(".png", "").lower()
        slug_map = {
            "log": "the-log",
            "snowball": "giant-snowball",
            "barbbarrel": "barbarian-barrel",
            "skellies": "skeletons",
            "3m": "three-musketeers",
        }
        slug = slug_map.get(slug, slug.replace("_", "-"))
        spells.append(_resolve_name(slug, alt, index))
    return spells


def _parse_card_page(slug: str, html: str, index: dict[str, str]) -> dict:
    title_m = CARD_TITLE.search(html)
    name_ru = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else slug
    card_name = _resolve_name(slug, name_ru, index)

    counters: dict[str, dict[str, list[str]]] = {}
    synergy: dict[str, dict[str, list[str]]] = {}

    for list_id, block in CARD_LIST_BLOCK.findall(html):
        strong, partial = _parse_card_links(block, index)
        bucket = {"strong": strong, "partial": partial}
        if "cnt" in list_id:
            counters[list_id] = bucket
        elif "syn" in list_id:
            synergy[list_id] = bucket
        else:
            # unknown list — treat as counters if only one exists
            counters[list_id] = bucket

    # Normalize primary keys
    def _pick(mapping: dict, *keys: str) -> dict[str, list[str]] | None:
        for key in keys:
            if key in mapping:
                return mapping[key]
        return next(iter(mapping.values()), None) if mapping else None

    counters_attack = _pick(counters, "atkcnt", "defcnt") or {"strong": [], "partial": []}
    counters_defense = counters.get("defcnt") if "defcnt" in counters and "atkcnt" in counters else None
    synergy_general = _pick(synergy, "synergy", "defsyn") or {"strong": [], "partial": []}
    synergy_offense = _pick(synergy, "atksyn", "synergy") or {"strong": [], "partial": []}

    all_counter_names = set(counters_attack.get("strong", [])) | set(counters_attack.get("partial", []))
    if counters_defense:
        all_counter_names |= set(counters_defense.get("strong", [])) | set(counters_defense.get("partial", []))

    return {
        "slug": slug,
        "name": card_name,
        "name_ru": name_ru,
        "url": BASE_URL.format(slug=slug),
        "not_killed_by_spells": _parse_spells_not_killing(html, index),
        "counters_vs_attack": counters_attack,
        "counters_vs_defense": counters_defense,
        "synergy_general": synergy_general if synergy_general != synergy_offense else None,
        "synergy_offense": synergy_offense,
        "counter_count": {
            "strong": len(counters_attack.get("strong", [])),
            "partial": len(counters_attack.get("partial", [])),
            "total_listed": len(all_counter_names),
        },
    }


def _add_anti_counters(cards: dict[str, dict]) -> None:
    all_names = sorted(cards.keys())
    for name, data in cards.items():
        listed: set[str] = set()
        for block in (data.get("counters_vs_attack"), data.get("counters_vs_defense")):
            if block:
                listed |= set(block.get("strong") or [])
                listed |= set(block.get("partial") or [])
        data["weak_or_no_counter"] = sorted(n for n in all_names if n not in listed and n != name)
        data["anti_counter_count"] = len(data["weak_or_no_counter"])


def fetch_all_slugs() -> list[str]:
    html = _fetch(STATS_URL)
    slugs = sorted(set(re.findall(r"/card/detail/([a-z0-9-]+)", html)))
    return slugs


def scrape(slugs: list[str], delay: float = 0.35) -> dict[str, dict]:
    index = _build_name_index()
    out: dict[str, dict] = {}
    total = len(slugs)
    for i, slug in enumerate(slugs, 1):
        url = BASE_URL.format(slug=slug)
        try:
            html = _fetch(url)
            data = _parse_card_page(slug, html, index)
            out[data["name"]] = data
            print(f"[{i}/{total}] {data['name']} — counters {data['counter_count']}")
        except urllib.error.HTTPError as e:
            print(f"[{i}/{total}] SKIP {slug}: HTTP {e.code}")
        except Exception as e:
            print(f"[{i}/{total}] ERROR {slug}: {e}")
        if i < total:
            time.sleep(delay)
    return out


def _py_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def write_module(cards: dict[str, dict], all_slugs: list[str]) -> None:
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        '"""',
        "Справочник контров и синергий карт (offline snapshot DeckShop).",
        "",
        "Источник: https://www.deckshop.pro/ru/",
        f"Обновлён (UTC): {scraped_at}",
        f"Карт в файле: {len(cards)}",
        "",
        "Обновление:",
        "  python scripts/scrape_deckshop_counters.py",
        "  python scripts/deckshop_add_anticounters.py  # опционально",
        "Проверка свежести:",
        "  python scripts/check_deckshop_data.py",
        "",
        "Рантайм: bot/services/deckshop_data.py (graceful fallback без HTTP).",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "DECKSHOP_SOURCE = {",
        f'    "site": {_py_str("https://www.deckshop.pro/ru/")},',
        f'    "scraped_at": {_py_str(scraped_at)},',
        f"    \"card_slugs_seen\": {len(all_slugs)},",
        f"    \"cards_parsed\": {len(cards)},",
        "}",
        "",
        "# card name (English) -> counter/synergy breakdown",
        "DECKSHOP_COUNTERS: dict[str, dict] = {",
    ]

    for name in sorted(cards):
        payload = json.dumps(cards[name], ensure_ascii=False, indent=4)
        payload = payload.replace(": null", ": None").replace(": true", ": True").replace(": false", ": False")
        indented = "\n".join("    " + line for line in payload.splitlines())
        lines.append(f"    {_py_str(name)}: {indented.strip()},")

    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("def get_deckshop_counters(card_name: str) -> dict | None:")
    lines.append('    """Return DeckShop counter data for a card (lookup by English name)."""')
    lines.append("    return DECKSHOP_COUNTERS.get(card_name)")
    lines.append("")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(cards)} cards)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", action="append", help="Scrape only specific slug(s)")
    parser.add_argument("--delay", type=float, default=0.35)
    args = parser.parse_args()

    if args.slug:
        slugs = args.slug
    else:
        print("Fetching card list from DeckShop...")
        slugs = fetch_all_slugs()
        print(f"Found {len(slugs)} slugs")

    cards = scrape(slugs, delay=args.delay)
    _add_anti_counters(cards)
    write_module(cards, slugs)


if __name__ == "__main__":
    main()
