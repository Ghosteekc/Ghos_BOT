"""Local renderer facts envelope + grounding (Qwen3 = voice layer only)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.local_renderer import (
    LOCAL_RENDERER_SYSTEM_PROMPT,
    LocalRendererPromptBuilder,
    attach_render_facts,
    build_facts_envelope,
    compact_facts_for_llm,
    find_ungrounded_card_mentions,
    ground_local_renderer_text,
)
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder
from bot.services.ghosteek_ai.safety.layer import SafetyLayer
from bot.services.ghosteek_ai.safety.local_renderer_validator import (
    LOCAL_RENDERER_INVALID_FALLBACK,
)
from bot.services.ghosteek_ai.voice import SYSTEM_PROMPT, coach_reply


def _ctx_with_tool(tool: str, data: dict, *, intent: str = "analyze_deck") -> AIContext:
    ctx = AIContext(raw_message="разбери колоду")
    ctx.intent.request = intent
    ctx.ok = True
    ctx.data = dict(data)
    ctx.tool_outputs = {
        tool: {"tool": tool, "ok": True, "data": dict(data), "call_id": "call_1"},
    }
    return ctx


def test_elixir_golem_cannot_become_trener():
    ctx = _ctx_with_tool(
        "card_info",
        {"name": "Elixir Golem", "name_ru": "Элик-Голем", "elixir": 3, "roles": []},
        intent="card_info",
    )
    envelope = build_facts_envelope(ctx)
    assert "Elixir Golem" in envelope["data"]["allowed_card_ids"]
    out = ground_local_renderer_text(
        "Elixir Golem — это elixir trainer, ставь его впереди.",
        envelope,
    )
    assert out == LOCAL_RENDERER_INVALID_FALLBACK


def test_allowlist_blocks_wizard():
    ctx = _ctx_with_tool(
        "deck_analysis",
        {
            "deck": [
                "Hog Rider",
                "Musketeer",
                "Ice Spirit",
                "Cannon",
                "Fireball",
                "Skeletons",
                "Ice Golem",
                "Zap",
            ],
            "recommendation": {
                "intent": {"primary_win": "Hog Rider"},
                "coaching": {"strengths": ["Цикл держит темп"], "play_style": "cycle"},
                "game_plan": {
                    "critical_weaknesses": ["Слабый anti-air"],
                    "how_to_win": "Дави Хогом",
                },
            },
            "synergy_score": 70,
        },
    )
    envelope = build_facts_envelope(ctx)
    allowed = envelope["data"]["allowed_card_ids"]
    assert "Hog Rider" in allowed
    assert find_ungrounded_card_mentions("Добавь Wizard в колоду.", allowed) == ["Wizard"]
    out = ground_local_renderer_text("Цикл ок. Добавь Wizard против воздуха.", envelope)
    assert out == LOCAL_RENDERER_INVALID_FALLBACK


def test_no_invented_card_when_not_in_toolresult():
    ctx = _ctx_with_tool(
        "deck_analysis",
        {
            "recommendation": {
                "intent": {},
                "coaching": {"strengths": ["Состав сбалансирован"]},
                "game_plan": {},
            },
            "synergy_score": 55,
        },
    )
    envelope = build_facts_envelope(ctx)
    assert envelope["data"]["allowed_card_ids"] == []
    out = ground_local_renderer_text("Бери Hog Rider и дави башню.", envelope)
    assert out == LOCAL_RENDERER_INVALID_FALLBACK


def test_avg_elixir_allowed_when_in_facts():
    ctx = _ctx_with_tool(
        "deck_analysis",
        {
            "deck": ["Hog Rider", "Musketeer"],
            "average_elixir": 2.6,
            "recommendation": {
                "intent": {"primary_win": "Hog Rider"},
                "coaching": {},
                "game_plan": {},
            },
        },
    )
    envelope = build_facts_envelope(ctx)
    assert any("2.6" in f for f in envelope["data"]["facts"])
    text = "Средняя стоимость 2.6 — колода лёгкая."
    assert ground_local_renderer_text(text, envelope) == text


def test_avg_elixir_blocked_when_missing():
    ctx = _ctx_with_tool(
        "deck_analysis",
        {
            "deck": ["Hog Rider", "Musketeer"],
            "recommendation": {
                "intent": {"primary_win": "Hog Rider"},
                "coaching": {"strengths": ["Хог давит"]},
                "game_plan": {},
            },
        },
    )
    envelope = build_facts_envelope(ctx)
    out = ground_local_renderer_text("Средняя стоимость 3.1 — тяжеловато.", envelope)
    assert out == LOCAL_RENDERER_INVALID_FALLBACK


def test_deck_analysis_facts_no_encyclopedia_in_prompt():
    ctx = _ctx_with_tool(
        "deck_analysis",
        {
            "deck": ["Hog Rider", "Musketeer"],
            "average_elixir": 2.6,
            "recommendation": {
                "intent": {"primary_win": "Hog Rider"},
                "coaching": {
                    "strengths": ["Воздушная защита: Musketeer"],
                    "play_style": "cycle",
                },
                "game_plan": {
                    "critical_weaknesses": ["недостаточно anti-air"],
                    "how_to_win": "Цикли Хога",
                },
            },
            "synergy_score": 72,
        },
    )
    messages = LocalRendererPromptBuilder().build(ctx)
    blob = "\n".join(m.content for m in messages)
    assert "CARDS:" in blob or "Hog Rider" in blob
    assert LOCAL_RENDERER_SYSTEM_PROMPT.split(".")[0] in messages[0].content
    assert SYSTEM_PROMPT not in blob


def test_coach_reply_does_not_inject_pick_tip():
    text = coach_reply("Вердикт короткий.", why="Причина из tool.", tip="")
    assert "Вердикт короткий" in text


def test_safety_local_grounding_blocks_wizard():
    ctx = _ctx_with_tool(
        "deck_analysis",
        {
            "deck": ["Hog Rider", "Musketeer"],
            "recommendation": {
                "intent": {"primary_win": "Hog Rider"},
                "coaching": {"strengths": ["Цикл"]},
                "game_plan": {},
            },
        },
    )
    attach_render_facts(ctx)
    out = SafetyLayer.apply("Цикл ок. Поставь Wizard в бэк.", ctx)
    # Gate режет галлюцинацию; Safety подставляет template ToolResult вместо холодного fallback.
    assert "Wizard" not in out
    assert out != "Цикл ок. Поставь Wizard в бэк."
    assert out != LOCAL_RENDERER_INVALID_FALLBACK


def test_cloud_agent_prompt_not_local_renderer():
    from bot.services.ghosteek_ai import service as svc
    from bot.services.ghosteek_ai.generator.llm_generator import QwenResponseGenerator
    from bot.services.ghosteek_ai.llm.base import LLMConfig

    provider = MagicMock()
    provider.config = LLMConfig(provider="groq", model="llama-3.3-70b")
    provider.supports_tools.return_value = True

    gen = svc._make_renderer("groq", provider)
    assert isinstance(gen, QwenResponseGenerator)
    assert not isinstance(gen.prompt_builder, LocalRendererPromptBuilder)
    assert isinstance(gen.prompt_builder, PromptBuilder)
    sys_msgs = gen.prompt_builder.build_system()
    assert SYSTEM_PROMPT.split("\n")[0] in sys_msgs[0].content

    local = svc._make_renderer("ollama", provider)
    assert isinstance(local.prompt_builder, LocalRendererPromptBuilder)


def test_resolve_groq_still_agent():
    from bot.services.ghosteek_ai import service as svc

    provider = MagicMock()
    provider.supports_tools.return_value = True
    with patch.object(svc, "_configured_mode", return_value="auto"):
        assert svc._resolve_runtime_mode(provider, backend="groq") == "agent"


def test_recommendation_no_swap_facts_and_style():
    ctx = _ctx_with_tool(
        "recommendation",
        {
            "deck": [
                "Executioner",
                "Mighty Miner",
                "Valkyrie",
                "Tornado",
                "Hog Rider",
                "The Log",
                "Fireball",
                "Guards",
            ],
            "synergy_score": 84.6,
            "recommendation": {
                "intent": {"primary_win": "Hog Rider", "min_air_defense": 1},
                "coaching": {"strengths": ["Exe-nado"], "play_style": "cycle"},
                "game_plan": {
                    "critical_weaknesses": ["min_air_defense"],
                    "how_to_win": "Hog pressure",
                },
                "improvement_plan": {"needed": False, "steps": []},
            },
        },
        intent="improve_deck",
    )
    envelope = build_facts_envelope(ctx)
    facts_blob = " ".join(envelope["data"]["facts"])
    assert "Замены не нужны" in facts_blob
    assert "min_air_defense" not in facts_blob.lower()
    assert "Основная проблема" not in facts_blob
    assert "Рекомендуемая замена" not in facts_blob
    compact = compact_facts_for_llm(envelope)
    assert "Замены не нужны" in compact
    assert "STYLE:" in compact
    assert "без свапов" in compact.lower() or "если в facts" in compact.lower()


def test_compact_facts_uses_russian_card_labels():
    ctx = _ctx_with_tool(
        "deck_builder",
        {
            "core": ["Balloon", "Mega Minion", "Tombstone"],
            "decks": [{"archetype": "Lava", "cards": ["Balloon", "Mega Minion", "Tombstone"]}],
        },
        intent="build_deck",
    )
    envelope = build_facts_envelope(ctx)
    compact = compact_facts_for_llm(envelope)
    assert "Шар" in compact
    assert "МегаМуха" in compact
    assert "Надгробие" in compact
    assert "Balloon" not in compact
    assert "Mega Minion" not in compact
    assert "Tombstone" not in compact
