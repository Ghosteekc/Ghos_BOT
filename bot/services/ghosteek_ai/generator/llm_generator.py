"""ResponseGenerator поверх LLMProvider (Ollama / Qwen)."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.messages import ChatMessage, ToolCallResult
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder
from bot.services.ghosteek_ai.llm.provider import (
    LLMProvider,
    OllamaProvider,
    QwenLLMProvider,
    get_llm_provider,
    ollama_config_from_settings,
    qwen_config_from_settings,
)
from bot.services.ghosteek_ai.llm.response_parser import ResponseParser


class LLMResponseGenerator:
    """PromptBuilder → LLMProvider → ResponseParser → text | ToolCallResult.

    Sync generate() оставлен для Protocol; LLM backends используют agenerate().
    """

    backend: str = "llm"

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        prompt_builder: PromptBuilder | None = None,
        response_parser: ResponseParser | None = None,
    ) -> None:
        self.provider = provider or OllamaProvider(ollama_config_from_settings())
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.response_parser = response_parser or ResponseParser()
        self.last_messages: list[ChatMessage] = []
        self.last_tool_call_result: ToolCallResult | None = None

    def build_messages(self, ctx: AIContext) -> list[ChatMessage]:
        self.last_messages = self.prompt_builder.build(ctx)
        return list(self.last_messages)

    def generate(self, ctx: AIContext) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}.generate is async-only for LLM backends. "
            "Use await agenerate(ctx) from the orchestrator."
        )

    async def agenerate(
        self,
        ctx: AIContext,
        *,
        tools: list | None = None,
        **kwargs,
    ) -> str | ToolCallResult:
        """Построить messages → model → parse.

        Если модель вернула tool_calls — вернуть ToolCallResult (не текст игроку).
        Иначе — финальный текст.
        """
        self.last_tool_call_result = None
        messages = self.build_messages(ctx)
        result = await self.provider.generate(messages, tools=tools, **kwargs)
        parsed = self.response_parser.parse(result)

        if parsed.has_tool_calls:
            tool_result = ToolCallResult(
                tool_calls=list(parsed.tool_calls),
                messages=list(messages),
                raw=parsed,
            )
            self.last_tool_call_result = tool_result
            return tool_result

        text = (parsed.text or "").strip()
        if not text:
            raise RuntimeError(f"{self.backend} returned empty text")
        return text


class OllamaResponseGenerator(LLMResponseGenerator):
    """Генератор через OllamaProvider (REST /api/chat)."""

    backend = "ollama"

    def __init__(self, provider: LLMProvider | None = None, **kwargs) -> None:
        super().__init__(
            provider or OllamaProvider(ollama_config_from_settings()),
            **kwargs,
        )


class QwenResponseGenerator(LLMResponseGenerator):
    """PromptBuilder → QwenLLMProvider (OpenAI-compatible) → ResponseParser.

    tool_calls → ToolCallResult (без ответа пользователю).
    Текст → str. Template остаётся fallback на уровне service.
    """

    backend = "qwen"

    def __init__(self, provider: LLMProvider | None = None, **kwargs) -> None:
        super().__init__(
            provider or QwenLLMProvider(qwen_config_from_settings()),
            **kwargs,
        )


# Alias по ТЗ / factory
OllamaGenerator = OllamaResponseGenerator
QwenGenerator = QwenResponseGenerator


def make_llm_response_generator(backend: str) -> LLMResponseGenerator:
    key = (backend or "").strip().lower()
    if key in {"qwen", "dashscope", "openai", "openai_compatible"}:
        return QwenResponseGenerator()
    if key in {"ollama", "local"}:
        return OllamaResponseGenerator()
    return LLMResponseGenerator(get_llm_provider(key))
