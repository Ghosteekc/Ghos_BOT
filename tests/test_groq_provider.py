"""Tests for Groq / OpenAI-compatible provider parsing and factory wiring."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot.services.ghosteek_ai.generator.factory import get_response_generator
from bot.services.ghosteek_ai.generator.llm_generator import QwenResponseGenerator
from bot.services.ghosteek_ai.generator.response import TemplateResponseGenerator
from bot.services.ghosteek_ai.llm.base import LLMConfig, ProviderError
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.llm.provider import (
    QwenLLMProvider,
    _messages_for_openai,
    get_llm_provider,
)
from bot.services.ghosteek_ai.llm.response_parser import ResponseParser


def test_factory_groq_returns_qwen_generator():
    gen = get_response_generator("groq")
    assert isinstance(gen, QwenResponseGenerator)


def test_template_has_agenerate():
    gen = get_response_generator("template")
    assert isinstance(gen, TemplateResponseGenerator)
    assert asyncio.iscoroutinefunction(gen.agenerate)


def test_get_llm_provider_groq():
    p = get_llm_provider(
        "groq",
        config=LLMConfig(
            provider="groq",
            model="qwen/qwen3.6-27b",
            base_url="https://api.groq.com/openai/v1",
            api_key="x",
        ),
    )
    assert p.name == "groq"
    assert p.supports_tools() is True


def test_parser_groq_reasoning_without_content():
    raw = {
        "model": "qwen/qwen3.6-27b",
        "choices": [{
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning": "Сначала разберём колоду, потом дам совет.",
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    parsed = ResponseParser().parse(raw)
    assert not parsed.has_tool_calls
    assert parsed.reasoning.startswith("Сначала")
    # reasoning не становится user-facing text
    assert parsed.text == ""


def test_parser_groq_content_null_with_tool_calls():
    raw = {
        "id": "chatcmpl-x",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning": "Нужен deck_analysis",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "deck_analysis",
                        "arguments": '{"cards":["Hog Rider"]}',
                    },
                }],
            },
        }],
    }
    parsed = ResponseParser().parse(raw)
    assert parsed.has_tool_calls
    assert parsed.tool_calls[0].name == "deck_analysis"
    assert parsed.text == ""
    assert parsed.reasoning.startswith("Нужен")


def test_parser_normal_content():
    raw = {
        "choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "  Привет!  "},
        }],
    }
    parsed = ResponseParser().parse(raw)
    assert parsed.text == "Привет!"
    assert not parsed.has_tool_calls


def test_messages_for_openai_include_reasoning():
    msgs = [
        ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            reasoning="think",
            tool_calls=[{
                "id": "c1",
                "type": "function",
                "function": {"name": "echo", "arguments": "{}"},
            }],
        )
    ]
    out = _messages_for_openai(msgs)
    assert out[0]["reasoning"] == "think"
    assert out[0]["tool_calls"]


def test_provider_empty_raises_provider_error_not_runtime():
    provider = QwenLLMProvider(
        LLMConfig(
            provider="groq",
            model="m",
            base_url="https://api.groq.com/openai/v1",
            api_key="sk-test",
        )
    )
    empty = {
        "choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": None},
        }],
    }
    # Simulate parse path via public parser then empty check logic
    parsed = provider._parser.parse(empty)
    assert not parsed.has_usable_output

    # Missing base url → ProviderError
    bad = QwenLLMProvider(LLMConfig(provider="groq", model="m", base_url="", api_key="x"))
    try:
        bad._chat_url()
        assert False, "expected ProviderError"
    except ProviderError as exc:
        assert exc.code == "LLM_BASE_URL_MISSING"
    except RuntimeError:
        assert False, "must not raise RuntimeError"


def test_provider_accepts_reasoning_only_via_parser_then_fill():
    """reasoning-only ответ парсится, но text остаётся пустым (не для UI)."""
    provider = QwenLLMProvider(
        LLMConfig(
            provider="groq",
            model="m",
            base_url="https://api.groq.com/openai/v1",
            api_key="sk",
        )
    )
    raw = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning": "Итоговый совет по колоде.",
            },
            "finish_reason": "stop",
        }],
    }
    parsed = provider._parser.parse(raw)
    assert parsed.reasoning.startswith("Итоговый")
    assert parsed.text == ""
    assert (parsed.reasoning or "").strip()  # есть сигнал для retry, не для UI


def test_groq_payload_uses_chat_completions_and_reasoning_format():
    provider = QwenLLMProvider(
        LLMConfig(
            provider="groq",
            model="qwen/qwen3.6-27b",
            base_url="https://api.groq.com/openai/v1",
            api_key="sk",
            extra={"enable_tools": True, "reasoning_format": "parsed"},
        )
    )
    assert provider._chat_url() == "https://api.groq.com/openai/v1/chat/completions"
    req = provider._normalize_request(
        [ChatMessage(role=MessageRole.USER, content="hi")],
    )
    payload = provider._payload(req, stream=False)
    assert payload["stream"] is False
    assert payload["reasoning_format"] == "parsed"
    assert payload["messages"][0]["role"] == "user"
