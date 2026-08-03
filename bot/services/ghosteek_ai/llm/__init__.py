"""LLM infrastructure for Ghosteek AI (providers, prompts, parsers).

Модель по умолчанию не вызывается. Прод-пайплайн остаётся на Template.
"""

from __future__ import annotations

from bot.services.ghosteek_ai.llm.base import LLMCapabilities, LLMConfig
from bot.services.ghosteek_ai.llm.messages import (
    ChatMessage,
    LLMGenerateRequest,
    LLMGenerateResult,
    LLMToolCall,
    MessageRole,
    messages_to_openai,
)
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder
from bot.services.ghosteek_ai.llm.provider import (
    LLMProvider,
    OllamaProvider,
    QwenLLMProvider,
    get_llm_provider,
)
from bot.services.ghosteek_ai.llm.response_parser import ResponseParser

__all__ = [
    "ChatMessage",
    "LLMCapabilities",
    "LLMConfig",
    "LLMGenerateRequest",
    "LLMGenerateResult",
    "LLMProvider",
    "LLMToolCall",
    "MessageRole",
    "OllamaProvider",
    "PromptBuilder",
    "QwenLLMProvider",
    "ResponseParser",
    "get_llm_provider",
    "messages_to_openai",
]
