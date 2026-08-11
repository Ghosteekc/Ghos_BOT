"""is_flying vs can_target_air must stay independent."""
from __future__ import annotations

from bot.services.card_data import card_can_target_air, card_has_role, card_is_flying
from bot.services.card_profile import clear_card_profile_cache, get_card_profile
from bot.services.match_difficulty import _air_defense, _air_threats


def setup_function() -> None:
    clear_card_profile_cache()


def test_flying_air_attacker():
    p = get_card_profile("Baby Dragon")
    assert p.is_flying is True
    assert p.can_target_air is True
    assert card_is_flying("Baby Dragon")
    assert card_can_target_air("Baby Dragon")


def test_flying_without_anti_air():
    p = get_card_profile("Balloon")
    assert p.is_flying is True
    assert p.can_target_air is False
    assert card_is_flying("Balloon")
    assert not card_can_target_air("Balloon")


def test_ground_anti_air_is_not_flying():
    for name in ("Musketeer", "Tesla", "Archers"):
        p = get_card_profile(name)
        assert p.is_flying is False, name
        assert p.can_target_air is True, name
        assert not card_is_flying(name), name
        assert card_can_target_air(name), name


def test_ground_without_anti_air():
    p = get_card_profile("Knight")
    assert p.is_flying is False
    assert p.can_target_air is False


def test_building_anti_air_not_flying():
    p = get_card_profile("Inferno Tower")
    assert p.is_flying is False
    assert p.can_target_air is True


def test_legacy_air_role_means_anti_air_not_flying():
    """CARD_META role 'air' / synonym still maps to anti-air only."""
    assert card_has_role("Musketeer", "air") is True
    assert card_is_flying("Musketeer") is False


def test_air_threats_exclude_ground_aa():
    deck = ["Musketeer", "Tesla", "Balloon", "Knight", "Zap", "Fireball", "Ice Golem", "Hog Rider"]
    threats = _air_threats(deck)
    assert "Balloon" in threats
    assert "Musketeer" not in threats
    assert "Tesla" not in threats


def test_air_defense_includes_ground_aa():
    deck = ["Musketeer", "Tesla", "Balloon", "Knight"]
    defense = _air_defense(deck)
    assert "Musketeer" in defense
    assert "Tesla" in defense
    assert "Balloon" not in defense
