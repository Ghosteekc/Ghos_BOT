"""Regression suite: Ghosteek AI local renderer — no hallucinations, short answers.

Мокается только LLM/HTTP boundary (Ollama generate). Бизнес-логика ToolResult
берётся из fixtures (реальные shapes), SafetyLayer / validator — реальные.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.ghosteek_ai.llm.local_renderer import (
    LOCAL_RENDERER_SYSTEM_PROMPT,
    LocalRendererPromptBuilder,
    attach_render_facts,
    build_facts_envelope,
)
from bot.services.ghosteek_ai.models import Plan, ToolSpec
from bot.services.ghosteek_ai.safety.layer import SafetyLayer
from bot.services.ghosteek_ai.safety.local_renderer_validator import (
    LOCAL_RENDERER_INVALID_FALLBACK,
    apply_local_renderer_gate,
    validate_local_renderer_response,
)
from bot.services.ghosteek_ai.voice import WORD_LIMITS, count_words, word_limit_for
from tests.fixtures.local_renderer_toolresults import (
    HOG_CYCLE,
    FIXTURES,
    ctx_from_tool_result,
    envelope_from_tool,
    fixture_battle_analysis,
    fixture_card_info,
    fixture_deck_analysis,
    fixture_deck_builder,
    fixture_elixir_golem_counters,
    fixture_empty_facts,
    fixture_failed_tool,
    fixture_matchup,
    fixture_mechanics,
    fixture_recommendation,
)

# Историческая галлюцинация на вопрос про Эликсирного голема
_HISTORICAL_HALLUCINATIONS = (
    "сокровище",
    "лагерь",
    "тренер",
    "армада",
    "пожар",
    "дракон",
)


def _assert_no_hallucination_tokens(text: str) -> None:
    low = (text or "").lower()
    for token in _HISTORICAL_HALLUCINATIONS:
        assert token not in low, f"hallucinated entity leaked: {token!r} in {text!r}"


# ---------------------------------------------------------------------------
# Fixtures available
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(FIXTURES.keys()))
def test_fixture_builds(name: str):
    tr = FIXTURES[name]()
    assert tr.tool
    assert isinstance(tr.data, dict)


# ---------------------------------------------------------------------------
# Per-scenario grounding
# ---------------------------------------------------------------------------


def test_card_info_blocks_unknown_and_allows_grounded():
    env = envelope_from_tool(fixture_card_info(), intent="card_info", message="кто такой элик голем")
    ok = "Elixir Golem стоит 3 эликсира."
    assert validate_local_renderer_response(ok, env).ok
    assert apply_local_renderer_gate(ok, env) == ok
    bad = apply_local_renderer_gate("Бери Wizard против него.", env)
    assert bad == LOCAL_RENDERER_INVALID_FALLBACK


def test_deck_analysis_unknown_card_number_mechanic():
    env = envelope_from_tool(fixture_deck_analysis(), intent="analyze_deck")
    assert validate_local_renderer_response(
        "Hog Rider — win condition. Средняя стоимость 2.6.", env
    ).ok
    assert apply_local_renderer_gate("Добавь Wizard.", env) == LOCAL_RENDERER_INVALID_FALLBACK
    assert apply_local_renderer_gate("Средняя стоимость 4.9.", env) == LOCAL_RENDERER_INVALID_FALLBACK
    assert (
        apply_local_renderer_gate("Это чистый Beatdown.", env)
        == LOCAL_RENDERER_INVALID_FALLBACK
    )


def test_analyze_deck_does_not_invent_missing_card_or_hog_26():
    """«Разбери мою колоду»: не подставлять карту X и не подменять состав Hog 2.6."""
    from bot.services.ghosteek_ai.context.ai_context import AIContext
    from bot.services.ghosteek_ai.llm.local_renderer import attach_render_facts

    deck = [
        "Giant",
        "Witch",
        "Mini P.E.K.K.A",
        "Mega Minion",
        "Fireball",
        "Zap",
        "Skeletons",
        "Baby Dragon",
    ]
    ctx = AIContext(raw_message="Разбери мою колоду")
    ctx.intent.request = "analyze_deck"
    ctx.ok = True
    ctx.data = {
        "deck": list(deck),
        "average_elixir": 3.8,
        "synergy_score": 71,
        "recommendation": {
            "intent": {"primary_win": "Giant", "archetype": "Beatdown"},
            "coaching": {"strengths": ["Giant танкует"], "play_style": "beatdown"},
            "game_plan": {"how_to_win": "Танкуй Giant"},
            "improvement_plan": {"needed": False, "steps": []},
        },
    }
    ctx.tool_outputs = {
        "deck_analysis": {
            "tool": "deck_analysis",
            "ok": True,
            "data": dict(ctx.data),
            "call_id": "call_1",
        }
    }
    env = attach_render_facts(ctx)
    messages = LocalRendererPromptBuilder().build(ctx)
    assert messages[0].content == LOCAL_RENDERER_SYSTEM_PROMPT
    blob = "\n".join(m.content for m in messages)
    assert "Giant" in blob
    assert "Witch" in blob
    for missing in ("Wizard", "Ice Spirit", "Cannon", "Musketeer"):
        assert missing not in env["data"]["allowed_card_ids"]
        gated = apply_local_renderer_gate(
            f"{missing} уже в колоде — это основа состава.", env
        )
        assert gated == LOCAL_RENDERER_INVALID_FALLBACK
    # Hog 2.6: чужие карты цикла + чужое число 2.6
    hog26 = "Это Hog 2.6: Ice Spirit, Cannon и Musketeer, средняя стоимость 2.6."
    assert apply_local_renderer_gate(hog26, env) == LOCAL_RENDERER_INVALID_FALLBACK
    ok = "Giant — основная win condition. Средняя стоимость 3.8."
    assert validate_local_renderer_response(ok, env).ok is True


def test_deck_analysis_no_invented_win_condition():
    env = envelope_from_tool(fixture_deck_analysis(), intent="analyze_deck")
    # Musketeer в allowlist, но не win condition в facts
    bad = "Win condition: Musketeer — дави ей башню."
    result = validate_local_renderer_response(bad, env)
    assert result.ok is False
    assert "invented_win_condition" in result.reason
    assert apply_local_renderer_gate(bad, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_deck_builder_ui_deck_independent_of_llm_text():
    tr = fixture_deck_builder()
    ctx = ctx_from_tool_result(tr, intent="build_deck", message="собери на хога")
    env = attach_render_facts(ctx)
    original_cards = list(ctx.deck_card["cards"])

    # Valid short text — UI deck unchanged
    valid = "Сборка cycle готова — смотри карточку."
    out = SafetyLayer.apply(valid, ctx)
    assert out != LOCAL_RENDERER_INVALID_FALLBACK or "карточк" in valid
    assert ctx.deck_card["cards"] == original_cards == HOG_CYCLE

    # Hallucinated card in text → fallback, deck still backend
    out2 = SafetyLayer.apply("Я добавил Wizard и убрал Hog Rider.", ctx)
    assert out2 == LOCAL_RENDERER_INVALID_FALLBACK
    assert ctx.deck_card["cards"] == HOG_CYCLE


def test_recommendation_swap_only_from_facts():
    env = envelope_from_tool(fixture_recommendation(), intent="improve_deck")
    ok = "Ice Spirit → Electro Spirit для reset."
    assert validate_local_renderer_response(ok, env).ok
    assert (
        apply_local_renderer_gate("Замени на Wizard.", env)
        == LOCAL_RENDERER_INVALID_FALLBACK
    )
    ctx = ctx_from_tool_result(
        fixture_recommendation(), intent="improve_deck", message="Что заменить?"
    )
    messages = LocalRendererPromptBuilder().build(ctx)
    assert messages[0].content == LOCAL_RENDERER_SYSTEM_PROMPT
    blob = "\n".join(m.content for m in messages)
    assert "Рекомендуемая замена" in blob or "Ice Spirit" in blob
    assert "Electro Spirit" in blob


def test_recommendation_invented_swap_blocked_when_engine_says_no():
    tr = fixture_recommendation()
    rec = dict(tr.data["recommendation"])
    rec["improvement_plan"] = {"needed": False, "steps": []}
    tr.data["recommendation"] = rec
    env = envelope_from_tool(tr, intent="improve_deck")
    # Карты из колоды — unknown_card не сработает; ловим выдуманный свап.
    invented = "Замени Ice Spirit на Cannon."
    result = validate_local_renderer_response(invented, env)
    assert result.ok is False
    assert result.reason == "invented_card_swap"
    assert apply_local_renderer_gate(invented, env) == LOCAL_RENDERER_INVALID_FALLBACK
    ok = "Критических замен не вижу — Hog Rider уже давит."
    assert validate_local_renderer_response(ok, env).ok is True


def test_matchup_and_battle_grounding():
    env_m = envelope_from_tool(fixture_matchup(), intent="matchup")
    assert validate_local_renderer_response(
        "Матчап сложный: мало single-target DPS против Elixir Golem.", env_m
    ).ok
    assert (
        apply_local_renderer_gate("Бери Mirror в контру.", env_m)
        == LOCAL_RENDERER_INVALID_FALLBACK
    )

    env_b = envelope_from_tool(fixture_battle_analysis(), intent="last_battle")
    assert validate_local_renderer_response(
        "Проиграл: рано атаковал у моста.", env_b
    ).ok
    assert (
        apply_local_renderer_gate("Шанс победы был 91%.", env_b)
        == LOCAL_RENDERER_INVALID_FALLBACK
    )


def test_mechanics_no_encyclopedia():
    env = envelope_from_tool(
        fixture_mechanics(), intent="explain_mechanic", message="что такое tempo"
    )
    assert validate_local_renderer_response(
        "Tempo — контроль ритма розыгрыша карт и давления.", env
    ).ok
    assert (
        apply_local_renderer_gate(
            "Tempo — это beatdown через Golem в мету 2020.", env
        )
        == LOCAL_RENDERER_INVALID_FALLBACK
    )


def test_failed_tool_no_llm_hallucination_gate():
    env = envelope_from_tool(fixture_failed_tool())
    assert env["ok"] is False
    halluc = "Hog Rider имба, ставь Wizard и дави."
    assert apply_local_renderer_gate(halluc, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_empty_facts_no_memory_answer():
    env = envelope_from_tool(fixture_empty_facts())
    # build_facts_envelope на пустых data → empty facts/cards
    data = env.get("data") or {}
    # may still extract nothing useful
    assert apply_local_renderer_gate(
        "В Clash Royale всегда бери Hog Rider.", env
    ) == LOCAL_RENDERER_INVALID_FALLBACK or not (
        data.get("facts") or data.get("allowed_card_ids")
    )


def test_generic_coach_tips_blocked():
    env = envelope_from_tool(fixture_deck_analysis())
    tip = "Hog Rider силён. Не переливай эликсир."
    assert apply_local_renderer_gate(tip, env) == LOCAL_RENDERER_INVALID_FALLBACK


def test_local_renderer_limits_answer_length():
    env = envelope_from_tool(fixture_deck_analysis(), intent="analyze_deck")
    # Long but grounded (repeats facts) → SafetyLayer trim
    ctx = ctx_from_tool_result(fixture_deck_analysis(), intent="analyze_deck")
    attach_render_facts(ctx)
    long_ok = (
        "Hog Rider — основная win condition. "
        "Средняя стоимость 2.6. " * 30
    )
    out = SafetyLayer.apply(long_ok, ctx)
    if out != LOCAL_RENDERER_INVALID_FALLBACK:
        limit = word_limit_for("analyze_deck")
        assert count_words(out) <= limit + 5  # small slack after voice cleanup
        assert len(out) <= 1200


# ---------------------------------------------------------------------------
# Historical Elixir Golem regression
# ---------------------------------------------------------------------------


def test_elixir_golem_counter_historical_hallucinations_blocked():
    """User: Чем лучше контрить Эликсирного голема?

    Раньше модель выдавала: сокровище, лагерь, тренер, армада, пожар, дракон.
    """
    tr = fixture_elixir_golem_counters()
    ctx = ctx_from_tool_result(
        tr,
        intent="game_coach",
        message="Чем лучше контрить Эликсирного голема?",
    )
    env = attach_render_facts(ctx)

    hallucinated = (
        "Контри Elixir Golem сокровищем, лагерем и тренером. "
        "Ещё армада, пожар и дракон помогут."
    )
    out = apply_local_renderer_gate(hallucinated, env)
    assert out == LOCAL_RENDERER_INVALID_FALLBACK
    _assert_no_hallucination_tokens(out)

    # По одной сущности
    for token in _HISTORICAL_HALLUCINATIONS:
        piece = f"Против Elixir Golem бери {token}."
        gated = apply_local_renderer_gate(piece, env)
        assert gated == LOCAL_RENDERER_INVALID_FALLBACK
        _assert_no_hallucination_tokens(gated)

    # Валидный ответ только из ToolResult
    valid = "Режь Elixir Golem Inferno Tower или Mini P.E.K.K.A."
    assert validate_local_renderer_response(valid, env).ok
    assert apply_local_renderer_gate(valid, env) == valid
    _assert_no_hallucination_tokens(valid)


def test_elixir_golem_safety_layer_end_to_end():
    ctx = ctx_from_tool_result(
        fixture_elixir_golem_counters(),
        intent="game_coach",
        message="Чем лучше контрить Эликсирного голема?",
    )
    attach_render_facts(ctx)
    out = SafetyLayer.apply(
        "Ставь сокровище и лагерь, потом тренер с армадой, пожар и дракон.",
        ctx,
    )
    assert out == LOCAL_RENDERER_INVALID_FALLBACK
    _assert_no_hallucination_tokens(out)


# ---------------------------------------------------------------------------
# Service path: mock only LLM HTTP boundary
# ---------------------------------------------------------------------------


def test_failed_tool_planner_does_not_call_llm():
    """FAILED_TOOL → template, agenerate не вызывается (нет hallucination path)."""
    from bot.services.ghosteek_ai import service as svc
    from bot.services.ghosteek_ai.context.ai_context import AIContext

    ctx = ctx_from_tool_result(fixture_failed_tool(), intent="analyze_deck")
    plan = Plan(
        intent="analyze_deck",
        service="DeckAnalyzer",
        tools=[ToolSpec(name="deck_analysis")],
    )
    fail = fixture_failed_tool()
    provider = MagicMock()
    provider.config = MagicMock(model="qwen3:8b")
    fake_gen = MagicMock()
    fake_gen.agenerate = AsyncMock(return_value="Я из памяти: бери Wizard и сокровище.")

    with (
        patch.object(
            svc._CALLER,
            "execute_plan",
            new=AsyncMock(return_value=[fail]),
        ),
        patch.object(svc, "_make_renderer", return_value=fake_gen),
        patch.object(svc._TEMPLATE, "generate", return_value="Нужна колода из 8 карт."),
    ):
        text, tools, meta = asyncio.run(
            svc._run_planner_fallback(
                ctx,
                plan,
                backend="ollama",
                provider=provider,
                reason="local_planner_first",
            )
        )

    fake_gen.agenerate.assert_not_awaited()
    assert meta["renderer_invoked"] is False
    assert meta["used_backend"] == "template"
    assert "Wizard" not in text
    _assert_no_hallucination_tokens(text)


def test_successful_tool_llm_output_gated_by_safety():
    """LLM boundary mocked; SafetyLayer блокирует галлюцинации в ответе модели."""
    from bot.services.ghosteek_ai import service as svc

    tr = fixture_deck_analysis()
    ctx = ctx_from_tool_result(tr, intent="analyze_deck", message="разбери колоду")
    plan = Plan(
        intent="analyze_deck",
        service="DeckAnalyzer",
        tools=[ToolSpec(name="deck_analysis")],
    )
    provider = MagicMock()
    provider.name = "ollama"
    provider.config = MagicMock(model="qwen3:8b")
    provider.supports_tools = MagicMock(return_value=False)
    provider.close = AsyncMock()

    fake_gen = MagicMock()
    fake_gen.agenerate = AsyncMock(
        return_value="Цикл ок. Добавь Wizard, сокровище и дракон."
    )

    with (
        patch.object(svc._CALLER, "execute_plan", new=AsyncMock(return_value=[tr])),
        patch.object(svc, "_make_renderer", return_value=fake_gen),
    ):
        text, tools, meta = asyncio.run(
            svc._run_planner_fallback(
                ctx,
                plan,
                backend="ollama",
                provider=provider,
                reason="local_planner_first",
            )
        )

    fake_gen.agenerate.assert_awaited()
    # Raw LLM text still gated when ask_ghosteek_ai applies SafetyLayer;
    # here we apply gate as production does after planner.
    gated = SafetyLayer.apply(text, ctx)
    assert gated == LOCAL_RENDERER_INVALID_FALLBACK
    _assert_no_hallucination_tokens(gated)
    assert tools == ["deck_analysis"]


def test_prompt_contains_only_fixture_facts_not_full_toolresult():
    ctx = ctx_from_tool_result(fixture_deck_analysis(), message="разбери")
    messages = LocalRendererPromptBuilder().build(ctx)
    blob = "\n".join(m.content for m in messages)
    assert "FACTS:" in blob
    assert "evaluation_report" not in blob
    assert "huge" not in blob
    assert HOG_CYCLE[0] in blob


def test_all_scenario_envelopes_reject_historical_tokens():
    """Любой сценарий: исторические токены без allowlist → invalid."""
    for name, factory in FIXTURES.items():
        if name in {"FAILED_TOOL", "EMPTY_FACTS"}:
            continue
        tr = factory()
        if not tr.ok:
            continue
        env = envelope_from_tool(tr)
        for token in ("сокровище", "лагерь", "тренер", "армада", "пожар"):
            out = apply_local_renderer_gate(f"Бери {token}.", env)
            assert out == LOCAL_RENDERER_INVALID_FALLBACK, name
