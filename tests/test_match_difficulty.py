"""MatchDifficultyAnalyzer — сложность матчапа из структуры колод."""

from bot.services.match_difficulty import MatchDifficultyAnalyzer


def _deck(names: list[str]) -> list[str]:
    assert len(names) == 8
    return names


def test_hard_hog_vs_double_building_air():
    """Два ответа на Hog + нет punish после FB + воздух → очень сложно."""
    user = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Fireball",
        "Ice Spirit", "Skeletons", "The Log", "Cannon",
    ])
    # Tesla + Cannon vs Hog; Balloon air; no FB value targets (no FM/Witch/etc.)
    opp = _deck([
        "Balloon", "Lava Hound", "Baby Dragon", "Mega Minion",
        "Tesla", "Cannon", "Zap", "Arrows",
    ])
    r = MatchDifficultyAnalyzer.analyze(user, opp)
    assert r.difficulty >= 70
    assert r.rating in {"Сложный", "Очень сложный"}
    joined = " ".join(r.reasons)
    assert "Хог" in joined or "ответа" in joined
    assert r.reasons, "высокий difficulty без причин запрещён"


def test_easy_when_opp_has_no_hog_answer():
    user = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    opp = _deck([
        "Giant", "Witch", "Wizard", "Minions",
        "Fireball", "Zap", "Archers", "Knight",
    ])
    r = MatchDifficultyAnalyzer.analyze(user, opp)
    # Без здания и без сильных ответов на Hog — проще
    joined = " ".join(r.reasons)
    assert "нет ответа на Хог" in joined or r.difficulty <= 55


def test_fireball_no_punish_reason():
    user = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    opp = _deck([
        "Royal Hogs", "Royal Recruits", "Heal Spirit", "Ice Spirit",
        "The Log", "Barbarian Barrel", "Knight", "Archers",
    ])
    r = MatchDifficultyAnalyzer.analyze(user, opp)
    joined = " ".join(r.reasons)
    # Нет FB-целей + у соперника punish WC
    assert "Фаербол" in joined or "наказать" in joined or r.difficulty >= 40


def test_rating_bands():
    assert MatchDifficultyAnalyzer.analyze(
        _deck(["Hog Rider", "Ice Golem", "Musketeer", "Cannon", "Ice Spirit", "Skeletons", "The Log", "Fireball"]),
        _deck(["Hog Rider", "Ice Golem", "Musketeer", "Cannon", "Ice Spirit", "Skeletons", "The Log", "Fireball"]),
    ).rating in {
        "Очень лёгкий", "Лёгкий", "Равный", "Сложный", "Очень сложный",
    }


def test_mirrored_decks_near_even():
    deck = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    r = MatchDifficultyAnalyzer.analyze(deck, deck)
    assert 30 <= r.difficulty <= 70
    assert r.rating in {"Лёгкий", "Равный", "Сложный"}
    assert r.reasons