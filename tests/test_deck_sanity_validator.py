"""Tests for Deck Sanity Validator."""

from __future__ import annotations

from bot.services.deck_sanity_validator import validate_deck_sanity
from bot.services.ghosteek_ai.voice_templates import template_analyze_deck, template_build_deck


def test_sanity_fails_without_win_condition():
    # Random defensive mush without a tower win-condition.
    deck = [
        "Knight",
        "Archers",
        "Skeletons",
        "Ice Spirit",
        "Cannon",
        "The Log",
        "Fireball",
        "Guards",
    ]
    report = validate_deck_sanity(deck)
    assert report.passed is False
    codes = {i.code for i in report.critical_issues}
    assert "win_condition" in codes or "game_plan_mismatch" in codes or "evaluation_fail" in codes


def test_template_build_honest_on_sanity_fail():
    # Нет полной колоды — честный отказ, без «как играть».
    text = template_build_deck({
        "core": ["Knight", "Archers", "Cannon", "Fireball"],
        "decks": [{
            "name": "Тест",
            "archetype": "Control",
            "sanity_report": {
                "passed": False,
                "checks": {"anti_air": False},
                "critical_messages": ["Колода слишком слабо защищается от воздуха."],
                "coach_verdict": "Колода слишком слабо защищается от воздуха.",
                "coach_why": "По составу видно дыру.",
            },
        }],
        "mode": "constructor",
    })
    assert "воздух" in text.lower() or "воздуха" in text.lower()
    assert "стабильн" not in text.lower() or "нестабильн" in text.lower()


def test_template_build_presents_complete_deck():
    mortar = [
        "Mortar",
        "Knight",
        "Archers",
        "Ice Spirit",
        "Skeletons",
        "Rocket",
        "The Log",
        "Tornado",
    ]
    text = template_build_deck({
        "core": ["Mortar"],
        "decks": [{
            "name": "Мортира цикл",
            "archetype": "Cycle",
            "cards": mortar,
            "sanity_report": {
                "passed": False,
                "critical_messages": [
                    "Сборка не соответствует заявленному стилю игры: нет роли dps."
                ],
                "coach_verdict": "Сборка не соответствует заявленному стилю игры: нет роли dps.",
                "coach_why": "Builder мог ошибиться — не буду оправдывать слабую сборку.",
            },
        }],
        "mode": "meta_templates",
    })
    low = text.lower()
    assert "собрал" in low
    assert "оправдывать" not in low
    assert "критическ" not in low
    assert "dps" not in low
    assert "закрой" not in low


def test_template_build_mentions_all_requested_core_cards():
    deck = [
        "Valkyrie",
        "Hog Rider",
        "Fire Spirit",
        "Skeletons",
        "Hunter",
        "Fireball",
        "The Log",
        "Firecracker",
    ]
    text = template_build_deck({
        "core": ["Valkyrie", "Hog Rider"],
        "decks": [{
            "name": "Cycle",
            "archetype": "Cycle",
            "cards": deck,
        }],
        "mode": "freeform_anchor",
    })
    low = text.lower().replace("ё", "е")
    assert "валькир" in low
    assert "хог" in low or "наездник" in low
    assert "вокруг" in low
    # Не акцентируем только одну карту местоимением «под неё».
    assert "под неё" not in low
    assert "все запрошенные" in low or "под них" in low


def test_template_analyze_blocks_play_plan_on_fail():
    text = template_analyze_deck({
        "recommendation": {
            "coaching": {
                "strengths": ["Сильное давление"],
                "play_style": "Контрпуш",
                "usage_tips": ["Атакуй сразу"],
            },
            "game_plan": {"how_to_win": "Танк сзади"},
            "sanity_report": {
                "passed": False,
                "critical_messages": [
                    "В колоде отсутствует стабильный способ добивать башню."
                ],
                "coach_verdict": "В колоде отсутствует стабильный способ добивать башню.",
            },
            "intent": {"archetype": "Beatdown"},
        },
    })
    assert "добивать" in text.lower() or "башн" in text.lower()
    assert "Играй это как" not in text
