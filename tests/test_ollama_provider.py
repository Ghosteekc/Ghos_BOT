"""Tests for Ollama provider helpers and service fallback."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.llm.provider import (
    OllamaProvider,
    _messages_for_ollama,
)


def test_messages_for_ollama_maps_tool_to_user():
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM, content="sys"),
        ChatMessage(role=MessageRole.TOOL, content='{"ok":true}', name="battle_analysis"),
        ChatMessage(role=MessageRole.USER, content="hi"),
    ]
    out = _messages_for_ollama(msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1]["role"] == "user"
    assert "battle_analysis" in out[1]["content"]
    assert out[2]["role"] == "user"


def test_generate_answer_falls_back_to_template_on_ollama_error():
    from bot.services.ghosteek_ai import service as svc

    ctx = AIContext(raw_message="привет")
    ctx.ok = True
    ctx.intent.request = "clarify"
    ctx.intent.service = "Clarify"

    fake_gen = MagicMock()
    fake_gen.agenerate = AsyncMock(side_effect=RuntimeError("Ollama connection error"))

    with (
        patch.object(svc, "_configured_backend", return_value="ollama"),
        patch.object(svc, "get_response_generator", return_value=fake_gen),
        patch.object(svc._TEMPLATE, "generate", return_value="template answer") as tmpl,
    ):
        text, meta = asyncio.run(svc._generate_answer(ctx))

    assert text == "template answer"
    assert meta["used_backend"] == "template"
    assert meta["llm_backend"] == "ollama"
    assert meta["fallback_reason"]
    assert "Ollama connection error" in meta["fallback_reason"]
    tmpl.assert_called_once()
    fake_gen.agenerate.assert_awaited_once()

def test_ollama_provider_supports_stream():
    p = OllamaProvider()
    assert p.supports_stream() is True
    assert p.supports_tools() is True
