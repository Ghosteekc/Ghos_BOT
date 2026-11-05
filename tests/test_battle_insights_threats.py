"""Recurring loss threats stay grounded in the deck actually played."""

from types import SimpleNamespace

from bot.api.schemas import InsightsResponse
from bot.services import battle_insights


def _battle(*, user_cards: list[str], opponent_cards: list[str]) -> dict:
    return {
        "battleTime": "20260918T120000.000Z",
        "team": [{"tag": "#PLAYER", "crowns": 0, "cards": user_cards}],
        "opponent": [{"name": "Opponent", "crowns": 1, "cards": opponent_cards}],
    }


def test_loss_threats_count_recurring_cards_and_keep_played_deck_counter(monkeypatch) -> None:
    monkeypatch.setattr(battle_insights, "extract_deck", lambda side: list(side["cards"]))
    monkeypatch.setattr(
        battle_insights,
        "analyze_battle_list_item",
        lambda *_args, **_kwargs: SimpleNamespace(opponent_threats=["Tesla"]),
    )
    monkeypatch.setattr(
        battle_insights,
        "counters_in_deck",
        lambda _threat, deck: (["Earthquake"], []) if "Earthquake" in deck else ([], []),
    )
    monkeypatch.setattr(battle_insights, "local_counter_available", lambda: True)
    monkeypatch.setattr(battle_insights, "local_counter_has_card", lambda _card: True)
    monkeypatch.setattr(
        battle_insights,
        "_tactical_lines",
        lambda _user, _opponent: ["Дави после того, как Tesla раскрыта."],
    )

    deck_with_answer = ["Hog Rider", "Earthquake", "Ice Golem", "Cannon", "The Log", "Musketeer", "Ice Spirit", "Skeletons"]
    deck_without_answer = ["Hog Rider", "Fireball", "Valkyrie", "Cannon", "The Log", "Musketeer", "Ice Spirit", "Skeletons"]
    rows = battle_insights.build_loss_threats(
        [
            _battle(user_cards=deck_with_answer, opponent_cards=["Tesla"] * 8),
            _battle(user_cards=deck_without_answer, opponent_cards=["Tesla"] * 8),
        ],
        "#PLAYER",
    )

    assert len(rows) == 1
    assert rows[0]["card"] == "Tesla"
    assert rows[0]["losses"] == 2
    # The newest loss used Earthquake, so the displayed answer is truthful for
    # the representative played deck rather than borrowed from another deck.
    assert rows[0]["counter_status"] == "strong"
    assert rows[0]["counter_check_performed"] is True
    assert rows[0]["strong_counters"]
    assert rows[0]["tactics"] == ["Дави после того, как Tesla раскрыта."]


def test_loss_threats_marks_completed_lookup_without_match(monkeypatch) -> None:
    monkeypatch.setattr(battle_insights, "extract_deck", lambda side: list(side["cards"]))
    monkeypatch.setattr(
        battle_insights,
        "analyze_battle_list_item",
        lambda *_args, **_kwargs: SimpleNamespace(opponent_threats=["P.E.K.K.A"]),
    )
    monkeypatch.setattr(battle_insights, "counters_in_deck", lambda *_args: ([], []))
    monkeypatch.setattr(battle_insights, "local_counter_available", lambda: True)
    monkeypatch.setattr(battle_insights, "local_counter_has_card", lambda _card: True)
    monkeypatch.setattr(battle_insights, "_tactical_lines", lambda *_args: [])

    rows = battle_insights.build_loss_threats(
        [_battle(user_cards=["Hog Rider"] * 8, opponent_cards=["P.E.K.K.A"] * 8)],
        "#PLAYER",
    )

    assert rows[0]["counter_status"] == "not_found"
    assert rows[0]["counter_check_performed"] is True
    assert rows[0]["strong_counters"] == []
    assert rows[0]["partial_counters"] == []


def test_loss_threats_keeps_counter_error_unknown(monkeypatch) -> None:
    monkeypatch.setattr(battle_insights, "extract_deck", lambda side: list(side["cards"]))
    monkeypatch.setattr(
        battle_insights,
        "analyze_battle_list_item",
        lambda *_args, **_kwargs: SimpleNamespace(opponent_threats=["Tesla"]),
    )
    monkeypatch.setattr(battle_insights, "local_counter_available", lambda: True)
    monkeypatch.setattr(battle_insights, "local_counter_has_card", lambda _card: True)
    monkeypatch.setattr(
        battle_insights,
        "counters_in_deck",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("counter database unavailable")),
    )
    monkeypatch.setattr(battle_insights, "_tactical_lines", lambda *_args: [])

    rows = battle_insights.build_loss_threats(
        [_battle(user_cards=["Hog Rider"] * 8, opponent_cards=["Tesla"] * 8)],
        "#PLAYER",
    )

    assert rows[0]["counter_status"] == "unknown"
    assert rows[0]["counter_check_performed"] is False


def test_insights_report_marks_incomplete_loss_data_as_undetermined(monkeypatch) -> None:
    monkeypatch.setattr(battle_insights, "build_battle_insight", lambda *_args: None)

    report = battle_insights.build_insights_report(
        [_battle(user_cards=["Hog Rider"], opponent_cards=["Tesla"] * 8)],
        "#PLAYER",
    )

    assert report["analysis_status"] == "insufficient"
    assert report["analysis_message"].startswith("Не удалось определить")


def test_insights_report_marks_history_without_losses(monkeypatch) -> None:
    monkeypatch.setattr(battle_insights, "build_battle_insight", lambda *_args: None)
    battle = _battle(user_cards=[], opponent_cards=[])
    battle["team"][0]["crowns"] = 1
    battle["opponent"][0]["crowns"] = 0

    report = battle_insights.build_insights_report([battle], "#PLAYER")

    assert report["analysis_status"] == "no_losses"
    assert "нет подтверждённых поражений" in report["analysis_message"]


def test_insights_report_keeps_successful_report_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        battle_insights,
        "build_battle_insight",
        lambda *_args: {
            "won": False, "tags": ["threat"], "outcome": "loss",
            "opponent_name": "Opponent", "summary": "", "matchup_score": 0,
            "details": [], "timestamp": "",
        },
    )
    monkeypatch.setattr(battle_insights, "build_loss_threats", lambda *_args: [{"card": "Tesla"}])

    report = battle_insights.build_insights_report(
        [_battle(user_cards=[], opponent_cards=[])],
        "#PLAYER",
    )

    assert report["analysis_status"] == "ok"
    assert report["analysis_message"] is None


def test_insights_api_contract_distinguishes_no_battles_and_temporary_failure() -> None:
    no_battles = InsightsResponse(
        insights=[], patterns=[], threats=[],
        analysis_status="no_battles",
        analysis_message="Боёв пока нет. Сыграйте бой и обновите историю, чтобы появился разбор.",
    )
    failed = InsightsResponse(
        insights=[], patterns=[], threats=[],
        analysis_status="error",
        analysis_message="Не удалось определить — анализ временно недоступен. Попробуйте позже.",
    )

    assert no_battles.analysis_status == "no_battles"
    assert "Сыграйте бой" in (no_battles.analysis_message or "")
    assert failed.analysis_status == "error"
    assert "временно недоступен" in (failed.analysis_message or "")


def test_insights_api_contract_preserves_unknown_counter_state() -> None:
    payload = InsightsResponse(
        insights=[],
        threats=[{
            "card": "Tesla",
            "card_ru": "Тесла",
            "losses": 1,
            "counter_status": "unknown",
            "counter_check_performed": False,
        }],
        analysis_status="error",
        analysis_message="Не удалось определить — анализ временно недоступен.",
    ).model_dump()

    assert payload["threats"][0]["counter_status"] == "unknown"
    assert payload["threats"][0]["counter_check_performed"] is False
    assert payload["analysis_status"] == "error"


def test_loss_threats_excludes_wins_and_draws(monkeypatch) -> None:
    monkeypatch.setattr(battle_insights, "extract_deck", lambda side: list(side["cards"]))
    monkeypatch.setattr(
        battle_insights,
        "analyze_battle_list_item",
        lambda *_args, **_kwargs: SimpleNamespace(opponent_threats=["Tesla"]),
    )

    draw = _battle(user_cards=["Hog Rider"] * 8, opponent_cards=["Tesla"] * 8)
    draw["opponent"][0]["crowns"] = 0
    win = _battle(user_cards=["Hog Rider"] * 8, opponent_cards=["Tesla"] * 8)
    win["team"][0]["crowns"] = 2

    assert battle_insights.build_loss_threats([draw, win], "#PLAYER") == []
