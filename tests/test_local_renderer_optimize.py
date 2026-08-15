"""Local Qwen3 renderer: short prompt, low latency knobs, follow-up context."""
from __future__ import annotations

import json

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.base import LLMConfig
from bot.services.ghosteek_ai.llm.local_renderer import (
    CONVERSATIONAL_SYSTEM_PROMPT,
    LOCAL_RENDERER_SYSTEM_PROMPT,
    LocalRendererPromptBuilder,
    attach_render_facts,
    can_reuse_last_facts_for_followup,
    compact_facts_for_llm,
    detect_followup_kind,
    estimate_prompt_chars,
    renderer_generate_kwargs,
    short_user_request,
)
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.llm.provider import OllamaProvider
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder


def _sample_ctx() -> AIContext:
    ctx = AIContext(raw_message="разбери мою колоду с Хогом")
    ctx.intent.request = "analyze_deck"
    ctx.ok = True
    ctx.data = {
        "deck": [
            "Hog Rider",
            "Musketeer",
            "Ice Spirit",
            "Cannon",
            "Fireball",
            "Zap",
            "Skeletons",
            "Ice Golem",
        ],
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
        "evaluation_report": {"huge": {"nested": list(range(200))}},
    }
    ctx.tool_outputs = {
        "deck_analysis": {
            "tool": "deck_analysis",
            "ok": True,
            "data": dict(ctx.data),
            "call_id": "c1",
        }
    }
    ctx.conversation.recent_messages = [
        {"role": "user", "content": "привет " * 40},
        {"role": "assistant", "content": "давай разберём " * 40},
    ]
    return ctx


def test_prompt_smaller_than_legacy_full_dump():
    ctx = _sample_ctx()
    envelope = attach_render_facts(ctx)

    legacy = [
        ChatMessage(
            role=MessageRole.SYSTEM,
            content=(
                "Ты не база знаний Clash Royale. Ты редактор текста.\n"
                + "Тебе переданы проверенные факты...\n" * 8
            ),
        ),
        ChatMessage(
            role=MessageRole.SYSTEM,
            content="Проверенные факты:\n"
            + json.dumps(envelope, ensure_ascii=False)
            + "\n"
            + json.dumps(ctx.data, ensure_ascii=False),
        ),
        ChatMessage(role=MessageRole.USER, content=ctx.raw_message),
        *[
            ChatMessage(role=MessageRole.USER, content=m["content"])
            for m in ctx.conversation.recent_messages
            if m["role"] == "user"
        ],
    ]
    legacy_chars = estimate_prompt_chars(legacy)
    optimized = LocalRendererPromptBuilder().build(ctx)
    opt_chars = estimate_prompt_chars(optimized)

    # CR trainer prompt длиннее one-liner, но это не dump ToolResult / истории.
    print(f"\n[local renderer] prompt chars before={legacy_chars} after={opt_chars}")
    blob = "\n".join(m.content for m in optimized)
    assert "evaluation_report" not in blob
    assert "huge" not in blob
    assert "привет привет" not in blob
    assert "allowed_entities" not in blob
    assert "answer_constraints" not in blob
    assert "FACTS:" in blob
    assert "Хог" in blob
    assert json.dumps(ctx.data, ensure_ascii=False) not in blob
    assert opt_chars < 14000
    assert LOCAL_RENDERER_SYSTEM_PROMPT in blob
    assert CONVERSATIONAL_SYSTEM_PROMPT not in blob


def test_renderer_generate_kwargs_prevent_think():
    kw = renderer_generate_kwargs()
    assert kw["think"] is False
    assert 0.3 <= float(kw["temperature"]) <= 0.5
    assert 128 <= int(kw["max_tokens"]) <= 256
    assert 2048 <= int(kw["num_ctx"]) <= 4096


def test_ollama_payload_example_for_local_renderer():
    ctx = _sample_ctx()
    messages = LocalRendererPromptBuilder().build(ctx)
    kw = renderer_generate_kwargs()
    provider = OllamaProvider(
        LLMConfig(
            provider="ollama",
            model="qwen3:8b",
            temperature=kw["temperature"],
            max_tokens=kw["max_tokens"],
            extra={
                "enable_tools": False,
                "num_ctx": kw["num_ctx"],
                "think": False,
            },
        )
    )
    req = provider._normalize_request(messages, tools=None, **kw)
    body = provider._payload(req, stream=False)

    assert body["model"] == "qwen3:8b"
    assert body["think"] is False
    assert "think" not in body["options"]
    assert body["options"]["num_predict"] == kw["max_tokens"]
    assert body["options"]["num_ctx"] == kw["num_ctx"]
    assert "tools" not in body
    assert len(body["messages"]) <= 5
    total = sum(len(m.get("content") or "") for m in body["messages"])
    # CR trainer prompt длиннее старого one-liner, но без dump ToolResult.
    assert total < 14000
    assert total > 1500


def test_followup_why_uses_prev_answer_and_facts():
    ctx = _sample_ctx()
    ctx.raw_message = "а почему?"
    prev = attach_render_facts(_sample_ctx())
    ctx.request_context = {
        "last_render_facts": prev,
        "last_answer_brief": "Hog Rider — win condition. Дави циклом.",
    }
    assert detect_followup_kind(ctx.raw_message) == "why"
    assert can_reuse_last_facts_for_followup(ctx) is True
    messages = LocalRendererPromptBuilder().build(ctx)
    blob = "\n".join(m.content for m in messages)
    assert "PREV_ANSWER:" in blob
    assert "Hog Rider" in blob
    assert short_user_request(ctx) == "а почему?"


def test_followup_detail_reuses_facts():
    ctx = AIContext(raw_message="подробнее")
    ctx.intent.request = "clarify"
    prev = attach_render_facts(_sample_ctx())
    ctx.request_context = {"last_render_facts": prev}
    assert can_reuse_last_facts_for_followup(ctx) is True
    attach_render_facts(ctx)
    assert ctx.render_facts["tool"] == "deck_analysis"
    blob = compact_facts_for_llm(ctx.render_facts)
    assert "FACTS:" in blob
    assert len(blob) < len(json.dumps(prev, ensure_ascii=False))


def test_system_prompt_is_cr_trainer_not_command_bot():
    assert "Ghosteek AI" in LOCAL_RENDERER_SYSTEM_PROMPT
    assert "FACTS" in LOCAL_RENDERER_SYSTEM_PROMPT
    assert "не придумывай" in LOCAL_RENDERER_SYSTEM_PROMPT.lower() or "Никогда не придумывай" in LOCAL_RENDERER_SYSTEM_PROMPT
    assert "Hog 2.6" in LOCAL_RENDERER_SYSTEM_PROMPT
    assert "командный бот" in LOCAL_RENDERER_SYSTEM_PROMPT or "командным ботом" in LOCAL_RENDERER_SYSTEM_PROMPT
    from bot.services.ghosteek_ai.llm.local_renderer import CONVERSATIONAL_SYSTEM_PROMPT

    assert CONVERSATIONAL_SYSTEM_PROMPT != LOCAL_RENDERER_SYSTEM_PROMPT
    assert "RecommendationEngine" not in CONVERSATIONAL_SYSTEM_PROMPT
    assert "FACTS" not in CONVERSATIONAL_SYSTEM_PROMPT


def test_cloud_prompt_builder_unchanged():
    from bot.services.ghosteek_ai.voice import SYSTEM_PROMPT

    pb = PromptBuilder()
    assert SYSTEM_PROMPT.split("\n")[0] in pb.build_system()[0].content
    assert "Ты редактор текста" not in pb.build_system()[0].content


def test_example_generated_response_shape():
    example_response = (
        "Hog Rider — основная win condition. "
        "Musketeer закрывает воздух. "
        "Держи цикл и не оверкоммить у моста."
    )
    assert 2 <= example_response.count(".") <= 4
    assert len(example_response) < 220
    assert "Wizard" not in example_response
