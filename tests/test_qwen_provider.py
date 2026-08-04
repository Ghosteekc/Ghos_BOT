"""Tests for Qwen / OpenAI-compatible provider (no live API calls)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.generator.factory import get_response_generator
from bot.services.ghosteek_ai.generator.llm_generator import QwenResponseGenerator
from bot.services.ghosteek_ai.llm.messages import (
    ChatMessage,
    LLMGenerateResult,
    LLMToolCall,
    MessageRole,
    ToolCallResult,
)
from bot.services.ghosteek_ai.llm.provider import (
    QwenLLMProvider,
    QwenProvider,
    _messages_for_openai,
    qwen_config_from_settings,
)
from bot.services.ghosteek_ai.llm.response_parser import ResponseParser
from bot.services.ghosteek_ai.llm.base import LLMConfig


def test_qwen_provider_alias():
    assert QwenProvider is QwenLLMProvider


def test_messages_for_openai_roles():
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="sys"),
        ChatMessage(role=MessageRole.USER, content="hi"),
        ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[{
                "id": "c1",
                "type": "function",
                "function": {"name": "echo", "arguments": "{}"},
            }],
        ),
        ChatMessage(
            role=MessageRole.TOOL,
            content='{"ok":true}',
            name="echo",
            tool_call_id="c1",
        ),
    ]
    out = _messages_for_openai(msgs)
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user"
    assert out[2]["role"] == "assistant"
    assert out[2]["tool_calls"]
    assert out[3]["role"] == "tool"
    assert out[3]["tool_call_id"] == "c1"


def test_parser_openai_tool_calls():
    raw = {
        "model": "qwen-test",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
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
    assert parsed.tool_calls[0].arguments["cards"] == ["Hog Rider"]
    assert parsed.text == ""


def test_factory_creates_qwen():
    gen = get_response_generator("qwen")
    assert isinstance(gen, QwenResponseGenerator)
    assert gen.backend == "qwen"


def test_factory_creates_template():
    gen = get_response_generator("template")
    assert gen.__class__.__name__ == "TemplateResponseGenerator"


def test_qwen_agenerate_returns_text():
    provider = MagicMock()
    provider.generate = AsyncMock(
        return_value=LLMGenerateResult(text="  hello coach  ")
    )
    gen = QwenResponseGenerator(provider=provider)
    ctx = AIContext(raw_message="привет")
    out = asyncio.run(gen.agenerate(ctx))
    assert out == "hello coach"
    assert gen.last_tool_call_result is None


def test_qwen_agenerate_returns_tool_call_result():
    provider = MagicMock()
    provider.generate = AsyncMock(
        return_value=LLMGenerateResult(
            tool_calls=[LLMToolCall(id="c1", name="echo", arguments={})],
        )
    )
    gen = QwenResponseGenerator(provider=provider)
    ctx = AIContext(raw_message="анализ")
    out = asyncio.run(gen.agenerate(ctx, tools=[{"type": "function"}]))
    assert isinstance(out, ToolCallResult)
    assert out.has_tool_calls
    assert out.tool_calls[0].name == "echo"
    assert gen.last_tool_call_result is out


def test_qwen_generate_builds_openai_payload():
    cfg = LLMConfig(
        provider="qwen",
        model="qwen-test",
        base_url="https://example.test/v1",
        api_key="sk-test",
        temperature=0.2,
        max_tokens=128,
    )
    provider = QwenLLMProvider(cfg)
    req_messages = [ChatMessage(role=MessageRole.USER, content="hi")]
    req = provider._normalize_request(
        req_messages,
        tools=[{"type": "function", "function": {"name": "echo"}}],
        response_format={"type": "json_object"},
    )
    payload = provider._payload(req, stream=False)
    assert payload["model"] == "qwen-test"
    assert payload["messages"][0]["role"] == "user"
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 128
    assert payload["tools"]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream"] is False
    assert provider._chat_url() == "https://example.test/v1/chat/completions"


def test_qwen_missing_config_errors():
    from bot.services.ghosteek_ai.llm.base import ProviderError

    provider = QwenLLMProvider(
        LLMConfig(provider="qwen", model="m", base_url="", api_key="x")
    )
    try:
        provider._chat_url()
        assert False, "expected ProviderError"
    except ProviderError as exc:
        assert "LLM_BASE_URL" in str(exc)
        assert exc.code == "LLM_BASE_URL_MISSING"

    provider2 = QwenLLMProvider(
        LLMConfig(provider="qwen", model="m", base_url="https://x/v1", api_key="")
    )
    try:
        provider2._headers()
        assert False, "expected ProviderError"
    except ProviderError as exc:
        assert "LLM_API_KEY" in str(exc)
        assert exc.code == "LLM_API_KEY_MISSING"


def test_qwen_config_from_settings_defaults():
    cfg = qwen_config_from_settings()
    assert cfg.provider in {"qwen", "groq"}
    assert cfg.model  # default / env model set
