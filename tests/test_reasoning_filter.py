"""Unit tests for ReasoningFilter — CoT / tool planning never reaches the user."""

from __future__ import annotations

from bot.services.ghosteek_ai.llm.reasoning_filter import (
    ReasoningFilter,
    finalize_user_facing_text,
)
from bot.services.ghosteek_ai.llm.response_parser import ResponseParser


def test_normal_russian_coach_answer_passes():
    text = "Дави Хогом после защиты. Не лей эликсир в никуда — жди контратаку."
    f = ReasoningFilter()
    assert f.is_final_answer(text)
    assert f.accept_or_none(text) == text


def test_normal_short_answer_passes():
    text = "Привет! Чем помочь по колоде?"
    assert ReasoningFilter().is_final_answer(text)


def test_english_i_need_to_blocked():
    text = "I need to analyze the deck before answering."
    f = ReasoningFilter()
    assert f.is_internal_reasoning(text)
    assert f.accept_or_none(text) is None


def test_english_the_user_wants_blocked():
    text = "The user wants a Hog cycle recommendation."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_english_available_tools_blocked():
    text = "Looking at available tools, I should call deck_analysis."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_english_ill_call_blocked():
    text = "I'll call the battle_analysis tool next."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_english_lets_think_blocked():
    text = "Let's think step by step about the matchup."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_react_thought_action_blocked():
    text = "Thought: need a tool\nAction: deck_analysis"
    assert ReasoningFilter().is_internal_reasoning(text)


def test_chain_of_thought_marker_blocked():
    text = "Reasoning: first check elixir, then answer."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_planner_system_prompt_blocked():
    text = "According to the system prompt and Planner, I will proceed."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_previous_tool_failed_blocked():
    text = "The previous tool failed, so I should retry."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_russian_mne_nuzhno_blocked():
    text = "Мне нужно сначала вызвать deck_analysis, потом ответить."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_russian_polzovatel_hochet_blocked():
    text = "Пользователь хочет разбор боя, поэтому я вызову инструмент."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_russian_dostupnye_instrumenty_blocked():
    text = "Смотрю доступные инструменты и решаю, что вызвать."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_russian_davai_podumaem_blocked():
    text = "Давай подумаем, какой tool подойдёт лучше."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_russian_sistemny_prompt_blocked():
    text = "По системному промпту я не должен врать про цифры."
    assert ReasoningFilter().is_internal_reasoning(text)


def test_finalize_never_uses_reasoning_field():
    out = finalize_user_facing_text(
        content="",
        reasoning="I need to call a tool first.",
    )
    assert out is None


def test_finalize_blocks_cot_content():
    out = finalize_user_facing_text(
        content="I should call tool deck_analysis now.",
        reasoning="",
    )
    assert out is None


def test_finalize_passes_clean_content():
    out = finalize_user_facing_text(
        content="Ставь Мушкетёра за Хога и не спеши.",
        reasoning="I need to think about this internally.",
    )
    assert out == "Ставь Мушкетёра за Хога и не спеши."


def test_parser_does_not_promote_reasoning_to_text():
    raw = {
        "choices": [{
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning": "I need to call deck_analysis.",
            },
        }],
    }
    parsed = ResponseParser().parse(raw)
    assert parsed.text == ""
    assert "need to call" in parsed.reasoning
    assert finalize_user_facing_text(
        content=parsed.text,
        reasoning=parsed.reasoning,
    ) is None
