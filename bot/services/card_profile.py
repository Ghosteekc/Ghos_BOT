"""Единый слой доступа к свойствам карт (CardProfile).

Источник правды для elixir / type / roles — ``bot/data/cards.json`` через
``deck_builder.loader.DeckDatabase``.

Legacy-справочники в ``card_data`` (CARD_META.role, WIN_CONDITIONS, COUNTERS,
SYNERGIES и локальные множества в analyzer/improver) пока сохраняются для
совместимости API; см. TODO в этом модуле и в card_data.

Не меняет алгоритмы builder / analyzer / improver — только чтение свойств.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class CardProfile:
    """Снимок свойств одной карты из единого каталога."""

    name: str
    elixir: int
    card_type: str
    roles: frozenset[str]

    def has_role(self, role: str) -> bool:
        """Проверка по полному roles[], не только primary.

        Учитывает синонимы уже существующих ролей (air ↔ air_defense,
        spell ↔ big_spell/small_spell). Новые роли не создаёт.
        """
        if role in ("air", "air_defense"):
            return "air_defense" in self.roles or "air" in self.roles
        if role == "spell":
            return (
                self.card_type == "spell"
                or "spell" in self.roles
                or "big_spell" in self.roles
                or "small_spell" in self.roles
            )
        if role == "building":
            return self.card_type == "building" or "building" in self.roles
        if role == "win_condition":
            return self.is_win_condition
        return role in self.roles

    @property
    def is_win_condition(self) -> bool:
        if "win_condition" in self.roles:
            return True
        # TODO: убрать зависимость от WIN_CONDITIONS, когда роль в JSON полная.
        from bot.services.card_data import WIN_CONDITIONS

        return self.name in WIN_CONDITIONS

    @property
    def is_building(self) -> bool:
        return self.card_type == "building" or "building" in self.roles

    @property
    def is_spell(self) -> bool:
        return self.card_type == "spell" or "spell" in self.roles

    @property
    def is_pure_spell(self) -> bool:
        """Заклинание без win-condition (как legacy is_pure_spell)."""
        if not self.is_spell:
            return False
        return not self.is_win_condition

    @property
    def is_air_defense(self) -> bool:
        return self.has_role("air_defense")

    @property
    def is_splash(self) -> bool:
        return "splash" in self.roles

    @property
    def is_cycle(self) -> bool:
        return "cycle" in self.roles

    @property
    def is_swarm(self) -> bool:
        if "swarm" in self.roles:
            return True
        from bot.services.card_data import SWARM_CARDS

        return self.name in SWARM_CARDS

    @property
    def is_offense_win_condition(self) -> bool:
        """Primary attack win — совпадает с legacy WIN_CONDITIONS membership."""
        from bot.services.card_data import WIN_CONDITIONS

        return self.name in WIN_CONDITIONS


def _profile_from_meta(name: str) -> CardProfile:
    """Fallback, если карты нет в cards.json."""
    from bot.services.card_data import CARD_META, WIN_CONDITIONS

    meta = CARD_META.get(name, {})
    elixir = int(meta.get("elixir", 4))
    card_type = str(meta.get("type", "troop"))
    base_role = str(meta.get("role", "support"))
    roles: set[str] = set()
    if base_role == "air":
        roles.add("air_defense")
    elif base_role:
        roles.add(base_role)
    if name in WIN_CONDITIONS:
        roles.add("win_condition")
    if card_type == "spell":
        roles.add("spell")
    if card_type == "building":
        roles.add("building")
    if not roles:
        roles.add("support")
    return CardProfile(
        name=name,
        elixir=elixir,
        card_type=card_type,
        roles=frozenset(roles),
    )


@lru_cache(maxsize=512)
def get_card_profile(name: str) -> CardProfile:
    """Единая точка доступа к свойствам карты."""
    try:
        from bot.services.deck_builder.loader import get_database

        rec = get_database().get_card(name)
    except Exception:
        rec = None

    if rec is not None:
        return CardProfile(
            name=name,
            elixir=int(rec.elixir),
            card_type=str(rec.type or "troop"),
            roles=frozenset(rec.roles),
        )
    return _profile_from_meta(name)
