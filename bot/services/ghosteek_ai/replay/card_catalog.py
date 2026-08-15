"""Card catalog for replay recognition — Clash API registry only, no invented names."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogCard:
    card_id: str
    card_name: str


class CardCatalog:
    """Allowed cards snapshot. Built from card_registry / API items only."""

    def __init__(self, cards: tuple[CatalogCard, ...] = ()) -> None:
        self._by_id: dict[str, CatalogCard] = {}
        self._by_name: dict[str, CatalogCard] = {}
        for card in cards:
            self._by_id[card.card_id] = card
            self._by_name[_norm(card.card_name)] = card

    def __len__(self) -> int:
        return len(self._by_name)

    def all_cards(self) -> tuple[CatalogCard, ...]:
        return tuple(self._by_name.values())

    def resolve(self, *, card_id: str | None = None, card_name: str | None = None) -> CatalogCard | None:
        if card_id is not None:
            key = str(card_id).strip()
            found = self._by_id.get(key)
            if found:
                return found
        if card_name:
            found = self._by_name.get(_norm(card_name))
            if found:
                return found
        return None

    def contains(self, card_id: str, card_name: str) -> bool:
        resolved = self.resolve(card_id=card_id, card_name=card_name)
        if resolved is None:
            return False
        return resolved.card_id == str(card_id).strip() and _norm(resolved.card_name) == _norm(card_name)

    @classmethod
    def from_registry_snapshot(cls, cards_by_name: dict[str, dict] | None) -> CardCatalog:
        items: list[CatalogCard] = []
        for info in (cards_by_name or {}).values():
            if not isinstance(info, dict):
                continue
            name = str(info.get("name") or "").strip()
            raw_id = info.get("id")
            if not name or raw_id is None:
                continue
            items.append(CatalogCard(card_id=str(int(raw_id)), card_name=name))
        return cls(tuple(items))

    @classmethod
    def from_loaded_registry(cls) -> CardCatalog:
        from bot.services import card_registry

        snapshot = getattr(card_registry, "_cards_by_name", None)
        return cls.from_registry_snapshot(snapshot if isinstance(snapshot, dict) else {})


def _norm(name: str) -> str:
    return name.strip().lower()
