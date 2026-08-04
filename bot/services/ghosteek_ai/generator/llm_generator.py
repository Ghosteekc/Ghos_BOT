"""ResponseGenerator поверх LLMProvider (Ollama / Qwen / Groq)."""

from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.base import ProviderError
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole, ToolCallResult
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder
from bot.services.ghosteek_ai.llm.provider import (
    LLMProvider,
    OllamaProvider,
    QwenLLMProvider,
    get_llm_provider,
    ollama_config_from_settings,
    qwen_config_from_settings,
)
from bot.services.ghosteek_ai.llm.reasoning_filter import (
    FINAL_ANSWER_RETRY_PROMPT,
    DEFAULT_REASONING_FILTER,
    finalize_user_facing_text,
)
from bot.services.ghosteek_ai.llm.response_parser import ResponseParser


class LLMResponseGenerator:
    """PromptBuilder → LLMProvider → ResponseParser → ReasoningFilter → text.

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
        """Построить messages → model → parse → ReasoningFilter.

        tool_calls → ToolCallResult (не текст игроку).
        Reasoning / CoT → retry за финальным ответом, иначе ProviderError.
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

        final = finalize_user_facing_text(
            content=parsed.text,
            reasoning=parsed.reasoning,
            filter=DEFAULT_REASONING_FILTER,
        )
        if final:
            return final

        # Один retry: явно просим финальный ответ без внутренних рассуждений.
        retry_messages = list(messages) + [
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=(parsed.text or "").strip(),
                reasoning=(parsed.reasoning or "").strip() or None,
            ),
            ChatMessage(role=MessageRole.USER, content=FINAL_ANSWER_RETRY_PROMPT),
        ]
        retry = await self.provider.generate(retry_messages, tools=None)
        retry_parsed = self.response_parser.parse(retry)
        if retry_parsed.has_tool_calls:
            raise ProviderError(
                f"{self.backend} returned tool_calls on final-answer retry",
                code="LLM_REASONING_BLOCKED",
            )
        final_retry = finalize_user_facing_text(
            content=retry_parsed.text,
            reasoning=retry_parsed.reasoning,
            filter=DEFAULT_REASONING_FILTER,
        )
        if final_retry:
            return final_retry

        raise ProviderError(
            f"{self.backend} returned internal reasoning instead of a final answer",
            code="LLM_REASONING_BLOCKED",
            details={
                "text_preview": (parsed.text or "")[:200],
                "has_reasoning": bool((parsed.reasoning or "").strip()),
            },
        )


class OllamaResponseGenerator(LLMResponseGenerator):
    """Генератор через OllamaProvider (REST /api/chat)."""

    backend = "ollama"

    def __init__(self, provider: LLMProvider | None = None, **kwargs) -> None:
        super().__init__(
            provider or OllamaProvider(ollama_config_from_settings()),
            **kwargs,
        )


class QwenResponseGenerator(LLMResponseGenerator):
    """PromptBuilder → OpenAI-compatible LLM → ResponseParser → ReasoningFilter."""

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
    if key in {"qwen", "dashscope", "openai", "openai_compatible", "groq"}:
        return QwenResponseGenerator()
    if key in {"ollama", "local"}:
        return OllamaResponseGenerator()
    return LLMResponseGenerator(get_llm_provider(key))
