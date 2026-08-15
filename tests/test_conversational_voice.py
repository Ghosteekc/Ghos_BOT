"""Conversational intent + factual grounding (без ослабления fact-lock)."""

from __future__ import annotations

import pytest

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.conversation.manager import ConversationManager
from bot.services.ghosteek_ai.conversation.state import ConversationState
from bot.services.ghosteek_ai.intents import (
    INTENT_ANALYZE_DECK,
    INTENT_BUILD_DECK,
    INTENT_CHAT,
    INTENT_CLARIFY,
    INTENT_EXPLAIN_MECHANIC,
    INTENT_GAME_COACH,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    detect_intent,
)
from bot.services.ghosteek_ai.llm.local_renderer import (
    CONVERSATIONAL_SYSTEM_PROMPT,
    CONVERSATIONAL_TOOL,
    LOCAL_RENDERER_SYSTEM_PROMPT,
    LocalRendererPromptBuilder,
    attach_conversational_facts,
    build_conversational_envelope,
    can_render_conversational,
    can_reuse_last_facts_for_followup,
    classify_chat_kind,
)
from bot.services.ghosteek_ai.planner.planner import INTENT_TOOL_MAP, Planner
from bot.services.ghosteek_ai.safety.local_renderer_validator import (
    LOCAL_RENDERER_UNKNOWN_TOPIC_FALLBACK,
    apply_local_renderer_gate,
    validate_local_renderer_response,
)


@pytest.mark.parametrize(
    "phrase",
    [
        "Привет",
        "Как дела?",
        "Как сам?",
        "Что делаешь?",
        "Ты тут?",
        "Что ты умеешь?",
        "Спасибо",
        "А ты вообще кто?",
        "Расскажи про себя",
        "Ахах",
        "Понятно",
        "Красавчик",
        "Кто ты?",
        "Ты хороший тренер?",
        "Мне скучно",
        "Я сегодня опять слил все бои",
    ],
)
def test_conversational_intent(phrase: str):
    d = detect_intent(phrase)
    assert d.intent == INTENT_CHAT, phrase
    plan = Planner.plan(d)
    assert plan.tools == []
    assert INTENT_TOOL_MAP[INTENT_CHAT] == []


@pytest.mark.parametrize(
    "phrase",
    [
        "Собери колоду с Ведьмой",
        "Сделай колоду с ведьмой",
        "Хочу деку вокруг ведьмы",
        "А можешь подобрать колоду через ведьму?",
        "Придумай колоду с ведьмой",
        "Давай соберём что-нибудь с ведьмой",
        "А можно ведьму оставить, а остальное под неё подобрать?",
    ],
)
def test_nl_build_deck_natural(phrase: str):
    d = detect_intent(phrase)
    assert d.intent == INTENT_BUILD_DECK, phrase
    assert "Witch" in d.cards, phrase


@pytest.mark.parametrize(
    "phrase,intent",
    [
        ("Что поставить вместо Мега-рыцаря?", INTENT_IMPROVE_DECK),
        ("Чем контрить Голема?", INTENT_GAME_COACH),
        ("Что такое темп?", INTENT_EXPLAIN_MECHANIC),
        ("Разбери мою колоду", INTENT_ANALYZE_DECK),
        ("Разбери последний бой", INTENT_LAST_BATTLE),
        ("Собери что-нибудь с ведьмой", INTENT_BUILD_DECK),
        ("А можно деку с ведьмой?", INTENT_BUILD_DECK),
        ("Я сегодня опять слил все бои, что делать?", INTENT_GAME_COACH),
        ("Почему ведьма считается слабой?", INTENT_GAME_COACH),
        ("Мне постоянно проигрывает ведьма", INTENT_GAME_COACH),
    ],
)
def test_cr_mode_natural_language(phrase: str, intent: str):
    d = detect_intent(phrase)
    assert d.intent == intent, (phrase, d.intent)


def test_conversational_envelope_no_cards():
    env = build_conversational_envelope("Привет")
    assert env["tool"] == CONVERSATIONAL_TOOL
    assert env["data"]["allowed_card_ids"] == []
    assert env["data"]["facts"]


def test_conversational_prompt_is_direct_qwen_not_facts():
    ctx = AIContext(raw_message="Как дела?")
    ctx.intent.request = INTENT_CHAT  # type: ignore[attr-defined]
    attach_conversational_facts(ctx)
    messages = LocalRendererPromptBuilder().build(ctx)
    blob = "\n".join(m.content for m in messages)
    assert "Ghosteek" in CONVERSATIONAL_SYSTEM_PROMPT
    assert "FACTS:" not in blob
    assert "Как дела?" in blob
    assert can_render_conversational(ctx) is True
    assert classify_chat_kind("Как дела?") == "how_are_you"
    assert messages[0].content == CONVERSATIONAL_SYSTEM_PROMPT
    assert LOCAL_RENDERER_SYSTEM_PROMPT not in blob
    assert "RecommendationEngine" not in blob


def test_mixed_greeting_and_replace_is_cr():
    d = detect_intent("Привет, как дела? Кстати, что лучше поставить вместо Ведьмы?")
    assert d.intent == INTENT_IMPROVE_DECK
    assert "Witch" in d.cards


def test_context_switch_smalltalk_does_not_reuse_cr_facts():
    ctx = AIContext(raw_message="А как дела?")
    ctx.intent.request = INTENT_CHAT  # type: ignore[attr-defined]
    ctx.request_context = {
        "last_render_facts": {
            "tool": "deck_builder",
            "ok": True,
            "data": {"facts": ["primary_win: Witch"], "allowed_card_ids": ["Witch"]},
        }
    }
    assert can_reuse_last_facts_for_followup(ctx) is False


def test_cr_followup_why_can_reuse_facts():
    ctx = AIContext(raw_message="А почему?")
    ctx.intent.request = INTENT_CHAT  # type: ignore[attr-defined]
    ctx.request_context = {
        "last_render_facts": {
            "tool": "recommendation",
            "ok": True,
            "data": {"facts": ["replace: Musketeer"], "allowed_card_ids": ["Musketeer"]},
        }
    }
    assert can_reuse_last_facts_for_followup(ctx) is True


def test_conversational_validator_blocks_invented_cards():
    env = attach_conversational_facts(AIContext(raw_message="Привет"))
    ok = validate_local_renderer_response(
        "Привет! Поставь Mega Knight и Electro Giant — это мета.",
        env,
    )
    assert ok.ok is False


def test_conversational_validator_allows_grounded_smalltalk():
    env = attach_conversational_facts(AIContext(raw_message="Спасибо"))
    text = "Всегда пожалуйста 👌 Могу ещё колоду или бой разобрать."
    ok = validate_local_renderer_response(text, env)
    assert ok.ok is True


def test_unknown_people_and_bloggers_are_chat_not_card():
    for phrase in (
        "Какие популярных блогеров по клеш роялю ты знаешь",
        "расскажи про Холдика",
        "расскажи про Нарека",
    ):
        d = detect_intent(phrase)
        assert d.intent == INTENT_CHAT, (phrase, d.intent)
        assert d.cards == []


def test_unknown_topic_prompt_says_dont_invent():
    ctx = AIContext(raw_message="расскажи про Холдика")
    ctx.intent.request = INTENT_CHAT  # type: ignore[attr-defined]
    attach_conversational_facts(ctx)
    messages = LocalRendererPromptBuilder().build(ctx)
    blob = "\n".join(m.content for m in messages)
    assert "не знаешь" in blob.lower() or "не знаеш" in blob.lower()
    assert "не выдумывай" in blob.lower()
    assert "FACTS:" not in blob


def test_validator_blocks_invented_person_as_card_or_strategy():
    env = attach_conversational_facts(AIContext(raw_message="расскажи про Холдика"))
    fake_strat = (
        "Holdik это стратегия, где ты стоишь на месте и защищаешь карты."
    )
    r = validate_local_renderer_response(fake_strat, env)
    assert r.ok is False
    assert "invented_identity" in r.reason

    env2 = attach_conversational_facts(AIContext(raw_message="расскажи про Нарека"))
    fake_card = (
        "Narek это карта, которая может наносить урон и снимать карту противника."
    )
    r2 = validate_local_renderer_response(fake_card, env2)
    assert r2.ok is False
    assert "invented_identity" in r2.reason

    honest = "Не знаю таких фактов — у меня нет данных про этого человека."
    assert validate_local_renderer_response(honest, env).ok is True
    assert apply_local_renderer_gate(fake_strat, env) == LOCAL_RENDERER_UNKNOWN_TOPIC_FALLBACK


def test_followup_improve_uses_last_deck():
    session = ConversationState()
    session.last_deck = [
        "Witch",
        "Hog Rider",
        "Ice Spirit",
        "Skeletons",
        "Cannon",
        "Fireball",
        "Log",
        "Musketeer",
    ]
    session.last_intent = INTENT_BUILD_DECK
    detected = detect_intent("А что тут заменить?")
    detected = ConversationManager.apply_followup_enrichment(
        session, detected, "А что тут заменить?", {}
    )
    assert detected.intent == INTENT_IMPROVE_DECK
    assert len(detected.cards) >= 8


def test_followup_keep_witch():
    session = ConversationState()
    session.last_deck = [
        "Witch",
        "Hog Rider",
        "Ice Spirit",
        "Skeletons",
        "Cannon",
        "Fireball",
        "Log",
        "Musketeer",
    ]
    session.last_intent = INTENT_BUILD_DECK
    detected = detect_intent("А ведьму можно оставить?")
    if detected.intent not in {INTENT_BUILD_DECK}:
        detected = ConversationManager.apply_followup_enrichment(
            session, detected, "А ведьму можно оставить?", {}
        )
    assert detected.intent == INTENT_BUILD_DECK
    assert "Witch" in detected.cards


def test_clarify_prompt_not_menu_command():
    from bot.services.ghosteek_ai.intents import CLARIFY_PROMPT

    assert "выбери одно" not in CLARIFY_PROMPT.lower()
    assert "Уточни одну цель" not in CLARIFY_PROMPT
