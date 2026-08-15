"""Unit tests: deterministic local renderer SafetyLayer gate."""
from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.local_renderer import (
    attach_render_facts,
    build_facts_envelope,
)
from bot.services.ghosteek_ai.safety.layer import SafetyLayer
from bot.services.ghosteek_ai.safety.local_renderer_validator import (
    LOCAL_RENDERER_INVALID_FALLBACK,
    apply_local_renderer_gate,
    validate_local_renderer_response,
)


def _envelope(
    *,
    tool: str = "deck_analysis",
    ok: bool = True,
    facts: list[str] | None = None,
    cards: list[str] | None = None,
    entities: list[str] | None = None,
) -> dict:
    facts = facts or []
    cards = cards or []
    entities = entities if entities is not None else list(cards) + list(facts)
    return {
        "tool": tool,
        "ok": ok,
        "data": {
            "facts": facts,
            "allowed_card_ids": cards,
            "allowed_entities": entities,
            "answer_constraints": [],
        },
    }


def test_valid_response_passes():
    env = _envelope(
        facts=["Основная win condition: Hog Rider", "Средняя стоимость: 2.6"],
        cards=["Hog Rider", "Musketeer"],
    )
    text = "Hog Rider — основная угроза. Средняя стоимость 2.6."
    result = validate_local_renderer_response(text, env)
    assert result.ok is True
    assert apply_local_renderer_gate(text, env) == text


def test_unknown_card_invalid():
    env = _envelope(
        facts=["Основная win condition: Hog Rider"],
        cards=["Hog Rider", "Musketeer"],
    )
    text = "Добавь Wizard против воздуха."
    result = validate_local_renderer_response(text, env)
    assert result.ok is False
    assert result.reason.startswith("unknown_card")
    assert apply_local_renderer_gate(text, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_unknown_number_invalid():
    env = _envelope(
        facts=["Основная win condition: Hog Rider", "Средняя стоимость: 2.6"],
        cards=["Hog Rider"],
    )
    text = "Средняя стоимость 3.1 — тяжеловато."
    result = validate_local_renderer_response(text, env)
    assert result.ok is False
    assert "unknown_number" in result.reason
    assert apply_local_renderer_gate(text, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_unknown_mechanic_invalid():
    env = _envelope(
        facts=["Основная win condition: Hog Rider", "Сильная сторона: цикл"],
        cards=["Hog Rider"],
    )
    text = "Это классический Beatdown, дави танком."
    result = validate_local_renderer_response(text, env)
    assert result.ok is False
    assert "unknown_mechanic" in result.reason
    assert apply_local_renderer_gate(text, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_mechanic_allowed_when_in_facts():
    env = _envelope(
        facts=["Стиль: beatdown", "Основная win condition: Golem"],
        cards=["Golem"],
    )
    text = "Играй как beatdown через Golem."
    assert validate_local_renderer_response(text, env).ok is True


def test_empty_toolresult_invalid():
    env = _envelope(facts=[], cards=[])
    text = "Колода выглядит сильной."
    result = validate_local_renderer_response(text, env)
    assert result.ok is False
    assert result.reason == "empty_toolresult_facts"
    assert apply_local_renderer_gate(text, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_failed_toolresult_invalid():
    env = _envelope(ok=False, facts=["x"], cards=["Hog Rider"])
    text = "Hog Rider силён."
    result = validate_local_renderer_response(text, env)
    assert result.ok is False
    assert result.reason == "tool_failed"
    assert apply_local_renderer_gate(text, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_empty_envelope_invalid():
    assert validate_local_renderer_response("ok", None).ok is False
    assert apply_local_renderer_gate("ok", {}) == LOCAL_RENDERER_INVALID_FALLBACK


def test_deck_builder_response_text_not_deck_source():
    """UI колода = backend; текст LLM не источник состава. Невалидные карты → fallback."""
    deck = [
        "Hog Rider",
        "Musketeer",
        "Ice Spirit",
        "Cannon",
        "Fireball",
        "The Log",
        "Skeletons",
        "Ice Golem",
    ]
    ctx = AIContext(raw_message="собери колоду на хога")
    ctx.intent.request = "build_deck"
    ctx.ok = True
    ctx.data = {
        "mode": "core",
        "decks": [{"name": "Hog Cycle", "archetype": "Cycle", "cards": deck}],
        "deck_card": {
            "title": "Hog Cycle",
            "archetype": "Cycle",
            "average_elixir": 2.6,
            "cards": deck,
        },
    }
    ctx.deck_card = dict(ctx.data["deck_card"])
    ctx.tool_outputs = {
        "deck_builder": {
            "tool": "deck_builder",
            "ok": True,
            "data": dict(ctx.data),
            "call_id": "c1",
        }
    }
    env = attach_render_facts(ctx)
    assert env["tool"] == "deck_builder"
    assert "Hog Rider" in env["data"]["allowed_card_ids"]

    # Valid: без выдуманных карт/чисел, UI по-прежнему берёт deck_card.
    valid = "Сборка cycle готова — смотри карточку колоды."
    assert validate_local_renderer_response(valid, env).ok is True
    assert ctx.deck_card["cards"] == deck

    # Invalid: LLM выдумала карту — весь ответ → fallback, deck_card не меняется.
    bad = "Я добавил Wizard вместо Musketeer."
    assert apply_local_renderer_gate(bad, env) == LOCAL_RENDERER_INVALID_FALLBACK
    assert ctx.deck_card["cards"] == deck


def test_deck_builder_allowlist_ignores_evaluator_inferno():
    """Карта из evaluation_report не считается частью собранной колоды."""
    deck = [
        "Barbarian Barrel",
        "Giant",
        "Mega Minion",
        "Poison",
        "Guards",
        "Tombstone",
        "Spear Goblins",
        "Miner",
    ]
    ctx = AIContext(raw_message="собери колоду со скелетной бочкой")
    ctx.intent.request = "build_deck"
    ctx.ok = True
    ctx.data = {
        "mode": "core",
        "core": ["Skeleton Barrel"],
        "decks": [{"name": "Control", "archetype": "Control", "cards": deck}],
        "deck_card": {
            "title": "Control",
            "archetype": "Control",
            "average_elixir": 3.1,
            "cards": deck,
        },
        "evaluation_report": {
            "gaps": [{"name": "Inferno Tower", "reason": "building"}],
        },
    }
    ctx.deck_card = dict(ctx.data["deck_card"])
    ctx.tool_outputs = {
        "deck_builder": {
            "tool": "deck_builder",
            "ok": True,
            "data": dict(ctx.data),
            "call_id": "c1",
        }
    }
    env = attach_render_facts(ctx)
    allowed = env["data"]["allowed_card_ids"]
    assert "Inferno Tower" not in allowed
    assert "Giant" in allowed
    bad = (
        "Собрал колоду с Barbarian Barrel. "
        "Miner и Inferno Tower обеспечат давление на фланг."
    )
    assert apply_local_renderer_gate(bad, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_safety_layer_local_uses_fallback_not_rewrite():
    ctx = AIContext(raw_message="разбери")
    ctx.intent.request = "analyze_deck"
    ctx.ok = False  # без успешного ToolResult — только холодный fallback
    ctx.render_facts = _envelope(
        facts=["Основная win condition: Hog Rider"],
        cards=["Hog Rider", "Musketeer"],
    )
    out = SafetyLayer.apply("Поставь Wizard в бэклайн.", ctx)
    assert out == LOCAL_RENDERER_INVALID_FALLBACK


def test_safety_layer_cloud_unchanged_path():
    """Без render_facts — cloud pipeline (не строгий local gate)."""
    ctx = AIContext(raw_message="привет")
    ctx.intent.request = "clarify"
    # Нет render_facts → ensure_coach_ending path, не LOCAL_RENDERER_INVALID_FALLBACK
    out = SafetyLayer.apply("Нужен чуть более конкретный вопрос.", ctx)
    assert out != LOCAL_RENDERER_INVALID_FALLBACK
    assert "конкретн" in out.lower() or len(out) > 0


def test_card_info_and_matchup_tools():
    # card_info
    env_card = _envelope(
        tool="card_info",
        facts=["Карта: Elixir Golem", "Стоимость эликсира: 3"],
        cards=["Elixir Golem"],
    )
    assert validate_local_renderer_response(
        "Elixir Golem стоит 3 эликсира.", env_card
    ).ok
    assert (
        apply_local_renderer_gate("Elixir Golem — это elixir trainer.", env_card)
        == LOCAL_RENDERER_INVALID_FALLBACK
    )

    # matchup
    env_m = _envelope(
        tool="matchup",
        facts=["Оценка матчапа: сложный", "Причина: мало anti-air"],
        cards=["Hog Rider", "Balloon"],
    )
    assert validate_local_renderer_response(
        "Матчап сложный: мало anti-air против Balloon.", env_m
    ).ok
    assert (
        apply_local_renderer_gate("Бери Inferno Dragon в контру.", env_m)
        == LOCAL_RENDERER_INVALID_FALLBACK
    )


def test_no_heuristic_partial_fix():
    """Invalid → полный fallback, не вырезание одного предложения."""
    env = _envelope(
        facts=["Сильная сторона: цикл"],
        cards=["Hog Rider"],
    )
    text = "Цикл ок. Добавь Wizard."
    out = apply_local_renderer_gate(text, env)
    assert out == LOCAL_RENDERER_INVALID_FALLBACK
    assert "Цикл" not in out
    assert "Wizard" not in out


def test_build_facts_envelope_tools_smoke():
    for tool, data, intent in (
        (
            "deck_analysis",
            {
                "deck": ["Hog Rider", "Musketeer"],
                "average_elixir": 2.6,
                "recommendation": {
                    "intent": {"primary_win": "Hog Rider"},
                    "coaching": {"strengths": ["темп"]},
                    "game_plan": {},
                },
            },
            "analyze_deck",
        ),
        (
            "recommendation",
            {
                "deck": ["Hog Rider"],
                "recommendation": {
                    "intent": {"primary_win": "Hog Rider"},
                    "improvement_plan": {
                        "needed": True,
                        "steps": [{"drop": "Ice Spirit", "pick": "Electro Spirit", "message": "swap"}],
                    },
                    "coaching": {},
                    "game_plan": {},
                },
            },
            "improve_deck",
        ),
        (
            "battle_analysis",
            {
                "won": False,
                "reasons": ["Рано атаковал"],
                "matchup_score": 42,
            },
            "last_battle",
        ),
    ):
        ctx = AIContext(raw_message="x")
        ctx.intent.request = intent
        ctx.ok = True
        ctx.data = data
        ctx.tool_outputs = {tool: {"tool": tool, "ok": True, "data": data}}
        env = build_facts_envelope(ctx)
        assert env["ok"] is True
        assert env["tool"] == tool


def test_invented_card_swap_rejected_when_not_needed():
    env = _envelope(
        tool="recommendation",
        facts=[
            "Замены не нужны. Не предлагай свап карт и не выдумывай причины замены.",
            "Основная win condition: Hog Rider",
        ],
        cards=["Valkyrie", "Guards", "Hog Rider", "Executioner", "Tornado"],
    )
    text = "Замени Valkyrie на Guards. Valkyrie слаба против Hog Rider."
    result = validate_local_renderer_response(text, env)
    assert result.ok is False
    assert result.reason == "invented_card_swap"
    assert apply_local_renderer_gate(text, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_no_swap_needed_voice_passes():
    env = _envelope(
        tool="recommendation",
        facts=[
            "Замены не нужны. Не предлагай свап карт и не выдумывай причины замены.",
            "Основная win condition: Hog Rider",
        ],
        cards=["Valkyrie", "Guards", "Hog Rider"],
    )
    text = "Критических замен не вижу — состав уже рабочий, Hog Rider давит."
    result = validate_local_renderer_response(text, env)
    assert result.ok is True
    assert apply_local_renderer_gate(text, env) == text


def test_real_recommended_swap_passes():
    env = _envelope(
        tool="recommendation",
        facts=[
            "Рекомендуемая замена: Ice Spirit → Electro Spirit",
            "Причина замены: нужен reset",
        ],
        cards=["Ice Spirit", "Electro Spirit"],
    )
    text = "Замени Ice Spirit на Electro Spirit — нужен reset."
    result = validate_local_renderer_response(text, env)
    assert result.ok is True
    assert apply_local_renderer_gate(text, env) == text
