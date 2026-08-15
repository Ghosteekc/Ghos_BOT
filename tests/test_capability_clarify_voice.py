"""Soft-clarify: живой голос через capability-facts, без свободной энциклопедии CR."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.local_renderer import (
    CAPABILITY_CLARIFY_TOOL,
    CONVERSATIONAL_SYSTEM_PROMPT,
    LOCAL_RENDERER_SYSTEM_PROMPT,
    LocalRendererPromptBuilder,
    attach_capability_clarify_facts,
    can_render_capability_clarify,
    is_soft_clarify_message,
)
from bot.services.ghosteek_ai.safety.local_renderer_validator import (
    validate_local_renderer_response,
)


def test_soft_clarify_detects_greetings():
    assert is_soft_clarify_message("Привет") is True
    assert is_soft_clarify_message("что умеешь?") is True
    assert is_soft_clarify_message("А что заменить?") is False
    assert is_soft_clarify_message("собери колоду с Ведьмой") is False


def test_capability_envelope_has_no_cards():
    env = attach_capability_clarify_facts(AIContext(raw_message="Привет"))
    assert env["tool"] == CAPABILITY_CLARIFY_TOOL
    data = env["data"]
    assert data["allowed_card_ids"] == []
    assert any("колод" in str(f).lower() for f in data["facts"])
    assert can_render_capability_clarify(AIContext(raw_message="Привет")) is True


def test_capability_prompt_is_grounded_and_human():
    ctx = AIContext(raw_message="Привет")
    attach_capability_clarify_facts(ctx)
    messages = LocalRendererPromptBuilder().build(ctx)
    blob = "\n".join(m.content for m in messages)
    assert "Ghosteek" in LOCAL_RENDERER_SYSTEM_PROMPT
    assert "живо" in LOCAL_RENDERER_SYSTEM_PROMPT.lower() or "человеч" in LOCAL_RENDERER_SYSTEM_PROMPT.lower()
    assert "FACTS:" in blob
    assert "Без карт" in blob or "без карт" in blob.lower()
    assert "RecommendationEngine" not in messages[0].content
    assert messages[0].content == CONVERSATIONAL_SYSTEM_PROMPT


def test_capability_validator_blocks_invented_cards():
    ctx = AIContext(raw_message="Привет")
    env = attach_capability_clarify_facts(ctx)
    ok = validate_local_renderer_response(
        "Привет! Замени Tornado на Fireball — так лучше воздух.",
        env,
    )
    assert ok.ok is False
    assert "unknown_card" in ok.reason or "banned" in ok.reason or "unknown" in ok.reason


def test_capability_validator_allows_grounded_greeting():
    ctx = AIContext(raw_message="Привет")
    env = attach_capability_clarify_facts(ctx)
    text = (
        "Привет! Я Ghosteek — помогу со сборкой колоды, разбором состава, "
        "матчапом или боем. Напиши одну задачу своими словами."
    )
    ok = validate_local_renderer_response(text, env)
    assert ok.ok is True
