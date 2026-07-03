"""Live meta deck analysis from top-ladder battle logs."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bot.config import settings
from bot.services.card_icons import cards_from_team, deck_card_info_from_parsed, parse_battle_card
from bot.services.card_names_ru import card_name_ru
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded, get_card_info
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient
from bot.services.deck_analyzer import analyze_deck
from bot.services.meta_decks import META_DECKS

logger = logging.getLogger(__name__)

_refresh_lock = asyncio.Lock()


@dataclass
class MetaCache:
    decks: list[dict] = field(default_factory=list)
    updated_at: datetime | None = None
    source: str = "static"

    def expired(self) -> bool:
        if self.updated_at is None:
            return True
        ttl = max(1, settings.meta_refresh_hours) * 3600
        return (datetime.now(timezone.utc) - self.updated_at).total_seconds() > ttl


_cache = MetaCache()


def _current_season_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _is_competitive_battle(battle: dict, player_tag: str) -> bool:
    btype = (battle.get("type") or "").lower()
    if btype not in ("pvp", "pathoflegend", "trail"):
        return False
    team = battle.get("team", [{}])[0]
    if team.get("tag", "").upper() != player_tag.upper():
        return False
    if len(team.get("cards", [])) != 8:
        return False
    if btype == "pathoflegend":
        return True
    trophies = int(team.get("startingTrophies") or 0)
    return trophies >= 6500


def _deck_set_key(cards: list[str]) -> frozenset[str]:
    return frozenset(cards)


def _order_key(cards: list[str]) -> tuple[str, ...]:
    return tuple(cards)


def _guess_deck_name(cards: list[str]) -> str:
    card_set = frozenset(cards)
    for meta in META_DECKS:
        if frozenset(meta.cards) == card_set:
            return meta.name
    stats = analyze_deck(cards)
    if stats.win_conditions:
        wc = card_name_ru(stats.win_conditions[0], short=True)
        if stats.avg_elixir <= 3.2:
            return f"{wc} Cycle"
        return wc
    return "Meta колода"


def _guess_category(cards: list[str]) -> str:
    for meta in META_DECKS:
        if frozenset(meta.cards) == frozenset(cards):
            return meta.category
    stats = analyze_deck(cards)
    if "Goblin Barrel" in cards or "Princess" in cards:
        return "bait"
    if stats.avg_elixir <= 3.2:
        return "cycle"
    if stats.avg_elixir >= 4.2:
        return "beatdown"
    if stats.buildings and len(stats.buildings) >= 2:
        return "control"
    return "meta"


def _merge_slot_variants(variants: list[list[dict]]) -> list[dict]:
    """Pick the most common card order and evolution/hero per slot."""
    if not variants:
        return []
    order_counts: Counter[tuple[str, ...]] = Counter()
    for variant in variants:
        order_counts[tuple(c["name"] for c in variant)] += 1
    best_order = order_counts.most_common(1)[0][0]
    matching = [v for v in variants if tuple(c["name"] for c in v) == best_order]
    base = matching[0] if matching else variants[0]
    merged: list[dict] = []
    for slot, card in enumerate(base):
        evo_votes: Counter[int] = Counter()
        hero_votes = 0
        icon_votes: Counter[str] = Counter()
        for variant in matching:
            if slot >= len(variant):
                continue
            item = variant[slot]
            if item["name"] != card["name"]:
                continue
            evo_votes[int(item.get("evolution_level") or 0)] += 1
            if item.get("is_hero"):
                hero_votes += 1
            if item.get("icon"):
                icon_votes[item["icon"]] += 1
        best_evo = evo_votes.most_common(1)[0][0] if evo_votes else 0
        is_hero = hero_votes > len(matching) / 2
        parsed = {
            "name": card["name"],
            "icon": icon_votes.most_common(1)[0][0] if icon_votes else card.get("icon", ""),
            "evolution_level": best_evo,
            "is_hero": is_hero,
            "cost": card.get("cost") or get_card_elixir(card["name"]),
            "slot": slot,
        }
        if not parsed["icon"]:
            reg = get_card_info(card["name"]) or {}
            icons = {
                "medium": reg.get("icon") or "",
                "evolutionMedium": reg.get("evolution_icon") or "",
                "heroMedium": reg.get("hero_icon") or "",
            }
            from bot.services.card_icons import pick_icon_urls

            parsed["icon"] = pick_icon_urls(
                icons,
                evolution_level=parsed["evolution_level"],
                hero_level=1 if is_hero else 0,
            )
        merged.append(parsed)
    return merged


async def _collect_player_tags(client: ClashRoyaleClient) -> tuple[list[dict], str]:
    tags: list[dict] = []
    source = "static"

    season = _current_season_id()
    paths = [
        f"/locations/global/pathoflegend/{season}/rankings/players?limit=50",
        "/locations/57000006/pathoflegend/players?limit=50",
        "/locations/57000249/pathoflegend/players?limit=30",
        "/locations/57000193/pathoflegend/players?limit=30",
        "/locations/57000249/rankings/players?limit=30",
    ]
    for path in paths:
        try:
            data = await client._request(path)
            items = data.get("items", []) if isinstance(data, dict) else []
            if items:
                tags.extend(items)
                source = path.split("?")[0]
                logger.info("Meta source: %s (%d players)", source, len(items))
        except ClashRoyaleAPIError as e:
            logger.debug("Meta rankings unavailable at %s: %s", path, e)

    if not tags:
        for raw_tag in settings.meta_seed_tags.split(","):
            tag = raw_tag.strip()
            if tag:
                tags.append({"tag": tag if tag.startswith("#") else f"#{tag}", "name": tag})
        source = "seed_tags"

    seen: set[str] = set()
    unique: list[dict] = []
    for item in tags:
        tag = (item.get("tag") or "").upper()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        unique.append(item)
    return unique[: settings.meta_top_players_scan], source


async def _refresh_meta() -> MetaCache:
    await ensure_cards_loaded()
    client = ClashRoyaleClient()
    deck_stats: dict[frozenset[str], dict] = defaultdict(
        lambda: {"wins": 0, "total": 0, "variants": []},
    )

    try:
        players, source = await _collect_player_tags(client)
        for player in players:
            tag = player.get("tag") or ""
            if not tag:
                continue
            try:
                battles = await client.get_battlelog(tag)
            except ClashRoyaleAPIError:
                continue
            tag_norm = tag.upper()
            for battle in battles:
                if not _is_competitive_battle(battle, tag_norm):
                    continue
                team = battle.get("team", [{}])[0]
                opponent = battle.get("opponent", [{}])[0]
                parsed = cards_from_team(team)
                if len(parsed) != 8:
                    continue
                names = [c["name"] for c in parsed]
                key = _deck_set_key(names)
                bucket = deck_stats[key]
                bucket["total"] += 1
                if team.get("crowns", 0) > opponent.get("crowns", 0):
                    bucket["wins"] += 1
                bucket["variants"].append(parsed)
            await asyncio.sleep(0.15)
    except ClashRoyaleAPIError as e:
        logger.warning("Meta refresh failed: %s", e)
    finally:
        await client.close()

    ranked = sorted(deck_stats.items(), key=lambda x: x[1]["total"], reverse=True)
    entries: list[dict] = []

    if len(ranked) >= 3:
        for i, (key, data) in enumerate(ranked[:12]):
            merged = _merge_slot_variants(data["variants"])
            if len(merged) != 8:
                continue
            names = [c["name"] for c in merged]
            card_infos = [deck_card_info_from_parsed(c, slot=idx) for idx, c in enumerate(merged)]
            elixirs = [c["cost"] for c in card_infos if c["cost"]]
            avg = round(sum(elixirs) / len(elixirs), 1) if elixirs else 0.0
            wr = round(data["wins"] / data["total"] * 100, 1) if data["total"] else 0.0
            usage = data["total"]
            entries.append({
                "id": 2000 + i,
                "name": _guess_deck_name(names),
                "cards": card_infos,
                "winrate": wr,
                "total_games": usage,
                "avg_elixir": avg,
                "type": "meta",
                "category": _guess_category(names),
                "deck_link": build_deck_share_link(names),
                "description": f"Встречается у топов: {usage} боёв · WR {wr:.0f}%",
            })
        if entries:
            return MetaCache(decks=entries, updated_at=datetime.now(timezone.utc), source=source)

    # Fallback: enriched static list
    static_entries: list[dict] = []
    for i, meta in enumerate(META_DECKS):
        cards = list(meta.cards)
        card_infos = []
        elixirs: list[float] = []
        for slot, name in enumerate(cards):
            info = get_card_info(name) or {}
            cost = info.get("elixir") or get_card_elixir(name)
            elixirs.append(float(cost))
            card_infos.append({
                "id": f"{name.lower().replace(' ', '-')}-{slot}",
                "name": name,
                "icon": info.get("icon") or "",
                "cost": int(cost),
                "evolution_level": 0,
                "is_hero": False,
                "slot": slot,
            })
        avg = round(sum(elixirs) / len(elixirs), 1) if elixirs else 0.0
        static_entries.append({
            "id": 1000 + i,
            "name": meta.name,
            "cards": card_infos,
            "winrate": 0.0,
            "total_games": 0,
            "avg_elixir": avg,
            "type": "meta",
            "category": meta.category,
            "deck_link": build_deck_share_link(cards),
            "description": meta.description,
        })
    return MetaCache(decks=static_entries, updated_at=datetime.now(timezone.utc), source="static")


async def get_live_meta_decks(*, force: bool = False) -> MetaCache:
    global _cache
    if not force and not _cache.expired() and _cache.decks:
        return _cache
    async with _refresh_lock:
        if not force and not _cache.expired() and _cache.decks:
            return _cache
        _cache = await _refresh_meta()
        return _cache


async def refresh_meta_background() -> None:
    try:
        await get_live_meta_decks(force=True)
        logger.info("Meta cache refreshed (%d decks, source=%s)", len(_cache.decks), _cache.source)
    except Exception:
        logger.exception("Background meta refresh failed")
