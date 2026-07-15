"""Загрузка и индексация базы колод (масштаб 50k+)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class DeckRecord:
    id: str
    name: str
    archetype: str
    avg_elixir: float
    cards: tuple[str, ...]
    popularity: int = 50


@dataclass
class CardRecord:
    elixir: int
    type: str
    roles: frozenset[str]


class DeckDatabase:
    """Индексированная база колод для быстрого поиска."""

    def __init__(self) -> None:
        self.decks: list[DeckRecord] = []
        self.cards: dict[str, CardRecord] = {}
        self.synergy_pairs: dict[frozenset[str], int] = {}
        self._by_card: dict[str, list[int]] = {}
        self._by_archetype: dict[str, list[int]] = {}

    def load(self) -> None:
        cards_path = DATA_DIR / "cards.json"
        decks_path = DATA_DIR / "decks.json"
        if cards_path.exists() and decks_path.exists():
            self._load_from_files(cards_path, decks_path)
            return
        self._load_from_meta_fallback()

    def _load_from_files(self, cards_path: Path, decks_path: Path) -> None:

        cards_data = json.loads(cards_path.read_text(encoding="utf-8"))
        decks_data = json.loads(decks_path.read_text(encoding="utf-8"))

        self.cards = {
            name: CardRecord(
                elixir=int(info["elixir"]),
                type=str(info.get("type", "troop")),
                roles=frozenset(info.get("roles", [])),
            )
            for name, info in cards_data.get("cards", {}).items()
        }

        for raw in decks_data.get("decks", []):
            cards = tuple(raw["cards"])
            if len(cards) != 8:
                continue
            rec = DeckRecord(
                id=str(raw["id"]),
                name=str(raw.get("name", "")),
                archetype=str(raw.get("archetype", "Meta")),
                avg_elixir=float(raw.get("avgElixir", 0)),
                cards=cards,
                popularity=int(raw.get("popularity", 50)),
            )
            idx = len(self.decks)
            self.decks.append(rec)
            self._by_archetype.setdefault(rec.archetype, []).append(idx)
            for card in cards:
                self._by_card.setdefault(card, []).append(idx)

        for key, score in decks_data.get("synergyPairs", {}).items():
            parts = key.split("|")
            if len(parts) == 2:
                self.synergy_pairs[frozenset(parts)] = int(score)

    def _load_from_meta_fallback(self) -> None:
        """Fallback если JSON ещё не сгенерирован."""
        from bot.services.card_data import CARD_META, get_card_elixir
        from bot.services.meta_decks import META_DECKS
        from scripts.generate_deck_builder_data import _roles_for, _deck_archetype

        for name, meta in CARD_META.items():
            self.cards[name] = CardRecord(
                elixir=int(meta.get("elixir", 4)),
                type=str(meta.get("type", "troop")),
                roles=frozenset(_roles_for(name, meta)),
            )
        for i, md in enumerate(META_DECKS):
            cards = tuple(md.cards)
            avg = round(sum(get_card_elixir(c) for c in cards) / 8, 2)
            rec = DeckRecord(
                id=f"meta-{md.key}",
                name=md.name,
                archetype=_deck_archetype(md),
                avg_elixir=avg,
                cards=cards,
                popularity=100 - i,
            )
            idx = len(self.decks)
            self.decks.append(rec)
            self._by_archetype.setdefault(rec.archetype, []).append(idx)
            for card in cards:
                self._by_card.setdefault(card, []).append(idx)

    def candidate_indices(self, core: list[str]) -> list[int]:
        """Кандидаты: пересечение индексов по картам ядра, иначе по архетипу."""
        if not self.decks:
            return []

        sets = [set(self._by_card.get(c, [])) for c in core]
        sets = [s for s in sets if s]
        if sets:
            inter = sets[0]
            for s in sets[1:]:
                inter &= s
            if inter:
                return sorted(inter)

        union: set[int] = set()
        for s in sets:
            union |= s
        if union:
            return sorted(union)

        return list(range(len(self.decks)))

    def get_card(self, name: str) -> CardRecord | None:
        return self.cards.get(name)


@lru_cache(maxsize=1)
def get_database() -> DeckDatabase:
    db = DeckDatabase()
    db.load()
    return db
