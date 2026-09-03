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

# Не используем lru_cache: при циклическом импорте (card_matchups → is_pure_spell →
# get_card_profile → get_database → package init → balance → card_matchups)
# fallback из CARD_META кэшировался навсегда и ломал big_spell/air_defense/анализ.
_PROFILE_CACHE: dict[str, "CardProfile"] = {}

# Airborne units only (not ground anti-air). Kept as fallback when cards.json
# lacks role "flying"; generator writes the same set into roles.
_FLYING_UNITS = frozenset({
    "Minions", "Minion Horde", "Mega Minion", "Inferno Dragon", "Baby Dragon",
    "Balloon", "Lava Hound", "Bats", "Skeleton Dragons", "Phoenix",
    "Flying Machine", "Electro Dragon", "Skeleton Barrel",
})


@dataclass(frozen=True)
class CardProfile:
    """Снимок свойств одной карты из единого каталога."""

    name: str
    elixir: int
    card_type: str
    roles: frozenset[str]

    def has_role(self, role: str) -> bool:
        """Проверка по полному roles[], не только primary.

        Legacy: role ``air`` is an *anti-air* synonym for ``air_defense``
        (CARD_META primary role), NOT ``is_flying``. Prefer ``is_flying`` /
        ``can_target_air`` for new code.
        """
        if role in ("air", "air_defense"):
            return "air_defense" in self.roles or "air" in self.roles
        if role == "flying":
            return self.is_flying
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
        """Legacy alias for can_target_air (role air_defense)."""
        return "air_defense" in self.roles or "air" in self.roles

    @property
    def can_target_air(self) -> bool:
        """True if this card can attack airborne targets (anti-air)."""
        return self.is_air_defense

    @property
    def is_flying(self) -> bool:
        """True if the card itself is an airborne unit — independent of anti-air."""
        if "flying" in self.roles:
            return True
        return self.name in _FLYING_UNITS

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


_SMALL_SPELL_META = frozenset({
    "Zap", "The Log", "Giant Snowball", "Barbarian Barrel", "Arrows", "Rage",
    "Royal Delivery", "Vines",
})
_BIG_SPELL_META = frozenset({
    "Fireball", "Poison", "Rocket", "Lightning", "Freeze", "Earthquake", "Tornado",
})
_AIR_META = frozenset({
    "Musketeer", "Mega Minion", "Inferno Dragon", "Minions", "Archers", "Dart Goblin",
    "Electro Wizard", "Ice Wizard", "Wizard", "Baby Dragon", "Executioner", "Hunter",
    "Tesla", "Inferno Tower", "Firecracker", "Mother Witch", "Flying Machine",
    "Magic Archer", "Phoenix", "Little Prince", "Archer Queen",
})


def _profile_from_meta(name: str) -> CardProfile:
    """Fallback during loader initialization; static catalog remains primary."""
    # ``get_database`` can be unavailable while deck_builder is importing.
    # Read the same canonical JSON directly before using the legacy metadata,
    # so a valid card never loses its role/type facts due to that import cycle.
    from bot.services.card_knowledge import load_card_catalog

    catalog_record = load_card_catalog().get(name)
    if isinstance(catalog_record, dict):
        return CardProfile(
            name=name,
            elixir=int(catalog_record["elixir"]),
            card_type=str(catalog_record["type"]),
            roles=frozenset(catalog_record["roles"]),
        )

    # Legacy fallback for a name absent from the canonical catalog.
    from bot.services.card_data import CARD_META, WIN_CONDITIONS

    meta = CARD_META.get(name, {})
    elixir = int(meta.get("elixir", 4))
    card_type = str(meta.get("type", "troop"))
    base_role = str(meta.get("role", "support"))
    roles: set[str] = set()
    if base_role == "air":
        roles.add("air_defense")
    elif base_role and base_role not in {"spell", "building"}:
        roles.add(base_role)
    if name in WIN_CONDITIONS:
        roles.add("win_condition")
    if card_type == "spell" or base_role == "spell":
        roles.add("spell")
        if name not in WIN_CONDITIONS:
            if name in _SMALL_SPELL_META or elixir <= 2:
                roles.add("small_spell")
            if name in _BIG_SPELL_META or (elixir >= 4 and name not in _SMALL_SPELL_META):
                roles.add("big_spell")
    if card_type == "building" or base_role == "building":
        roles.add("building")
    if name in _AIR_META or base_role == "air":
        roles.add("air_defense")
    if name in _FLYING_UNITS:
        roles.add("flying")
    if base_role == "splash":
        roles.add("splash")
    if not roles:
        roles.add("support")
    return CardProfile(
        name=name,
        elixir=elixir,
        card_type=card_type,
        roles=frozenset(roles),
    )


def clear_card_profile_cache() -> None:
    """Сброс после успешной загрузки DeckDatabase."""
    _PROFILE_CACHE.clear()


def get_card_profile(name: str) -> CardProfile:
    """Единая точка доступа к свойствам карты."""
    cached = _PROFILE_CACHE.get(name)
    if cached is not None:
        return cached

    rec = None
    db_ready = False
    try:
        from bot.services.deck_builder.loader import get_database

        db = get_database()
        db_ready = True
        rec = db.get_card(name)
    except Exception:
        # Цикл импорта / частичная инициализация — не кэшируем fallback.
        return _profile_from_meta(name)

    if rec is not None:
        profile = CardProfile(
            name=name,
            elixir=int(rec.elixir),
            card_type=str(rec.type or "troop"),
            roles=frozenset(rec.roles),
        )
        _PROFILE_CACHE[name] = profile
        return profile

    profile = _profile_from_meta(name)
    # Карты реально нет в каталоге — можно кэшировать meta.
    if db_ready:
        _PROFILE_CACHE[name] = profile
    return profile
