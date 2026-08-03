"""LLMProvider — абстракция + OllamaProvider (интерфейс без вызова модели)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from bot.services.ghosteek_ai.llm.base import LLMCapabilities, LLMConfig
from bot.services.ghosteek_ai.llm.messages import (
    ChatMessage,
    LLMGenerateRequest,
    LLMGenerateResult,
)


class LLMProvider(ABC):
    """Контракт LLM-бэкенда для Ghosteek AI.

    Реализации не должны знать про Builder / Battle / Recommendation —
    только messages in → text / tool_calls out.
    """

    name: str = "base"

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig(provider=self.name)

    @abstractmethod
    async def generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMGenerateResult:
        """Синхронный (с точки зрения API) полный ответ модели."""
        ...

    @abstractmethod
    async def stream_generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Поток текстовых чанков. Пустой async-iterator допустим, если stream не поддержан."""
        ...

    @abstractmethod
    def supports_tools(self) -> bool:
        ...

    @abstractmethod
    def supports_stream(self) -> bool:
        ...

    @abstractmethod
    async def close(self) -> None:
        """Освободить HTTP-клиент / ресурсы."""
        ...

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(tools=self.supports_tools(), stream=self.supports_stream())

    def _normalize_request(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMGenerateRequest:
        if isinstance(messages, LLMGenerateRequest):
            req = messages
            if tools is not None:
                req = LLMGenerateRequest(
                    messages=list(req.messages),
                    tools=tools,
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                    model=req.model,
                    extra=dict(req.extra),
                )
            return req
        return LLMGenerateRequest(
            messages=list(messages),
            tools=tools,
            temperature=kwargs.get("temperature", self.config.temperature),
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            model=kwargs.get("model") or self.config.model or None,
            extra={k: v for k, v in kwargs.items() if k not in {"temperature", "max_tokens", "model"}},
        )


class OllamaProvider(LLMProvider):
    """Ollama HTTP provider — интерфейс готов, вызов модели не подключён.

    TODO(ollama):
      - POST {base_url}/api/chat с messages
      - поддержка stream=true для stream_generate
      - tools (если модель/версия Ollama поддерживает)
    """

    name = "ollama"

    def __init__(self, config: LLMConfig | None = None) -> None:
        cfg = config or LLMConfig(
            provider="ollama",
            model="llama3.2",
            base_url="http://127.0.0.1:11434",
        )
        super().__init__(cfg)
        self._closed = False

    async def generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMGenerateResult:
        req = self._normalize_request(messages, tools=tools, **kwargs)
        del req  # будет телом HTTP-запроса
        # TODO(ollama): httpx/aiohttp → /api/chat → LLMGenerateResult
        raise NotImplementedError(
            "OllamaProvider.generate is not connected yet. "
            "Wire HTTP client to Ollama /api/chat before selecting backend=ollama."
        )

    async def stream_generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        req = self._normalize_request(messages, tools=tools, **kwargs)
        del req
        # TODO(ollama): stream=true и yield чанков
        raise NotImplementedError(
            "OllamaProvider.stream_generate is not connected yet."
        )
        # делает функцию async-generator для type-checkers
        if False:  # pragma: no cover
            yield ""

    def supports_tools(self) -> bool:
        # TODO(ollama): True, когда включим tool calling в Ollama
        return False

    def supports_stream(self) -> bool:
        # TODO(ollama): True после реализации stream_generate
        return False

    async def close(self) -> None:
        self._closed = True
        # TODO(ollama): await http_client.aclose()


class QwenLLMProvider(LLMProvider):
    """Заготовка Qwen / DashScope provider. Модель не подключена."""

    name = "qwen"

    def __init__(self, config: LLMConfig | None = None) -> None:
        cfg = config or LLMConfig(provider="qwen", model="")
        super().__init__(cfg)
        self._closed = False

    async def generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMGenerateResult:
        self._normalize_request(messages, tools=tools, **kwargs)
        raise NotImplementedError(
            "QwenLLMProvider.generate is not connected yet. "
            "Do not select backend=qwen until the client is wired."
        )

    async def stream_generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        self._normalize_request(messages, tools=tools, **kwargs)
        raise NotImplementedError("QwenLLMProvider.stream_generate is not connected yet.")
        if False:  # pragma: no cover
            yield ""

    def supports_tools(self) -> bool:
        return False

    def supports_stream(self) -> bool:
        return False

    async def close(self) -> None:
        self._closed = True


def get_llm_provider(name: str | None = None, *, config: LLMConfig | None = None) -> LLMProvider:
    """Фабрика провайдеров. Не вызывает модель."""
    key = (name or (config.provider if config else "ollama") or "ollama").strip().lower()
    if key in {"qwen", "dashscope"}:
        return QwenLLMProvider(config)
    if key in {"ollama", "local"}:
        return OllamaProvider(config)
    # неизвестный — безопасный ollama-stub
    return OllamaProvider(config)
