"""Bomb Tower is splash / anti-swarm (area bombs), not building-only."""

from bot.services.card_profile import clear_card_profile_cache, get_card_profile
from bot.services.deck_analyzer import analyze_deck


def test_bomb_tower_has_splash_role():
    clear_card_profile_cache()
    profile = get_card_profile("Bomb Tower")
    assert profile.is_splash
    assert profile.has_role("splash")
    assert profile.has_role("anti_swarm")
    assert profile.is_building


def test_hog_giant_deck_with_bomb_tower_has_splash_coverage():
    clear_card_profile_cache()
    deck = [
        "Royal Hogs",
        "Goblin Giant",
        "Archers",
        "Lightning",
        "Skeletons",
        "Electro Spirit",
        "Barbarian Barrel",
        "Bomb Tower",
    ]
    stats = analyze_deck(deck)
    assert stats.splash_coverage is True
