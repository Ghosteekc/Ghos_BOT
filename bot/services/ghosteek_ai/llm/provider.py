"""Ollama / Qwen message encoding helpers and LLMProvider implementations."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from bot.services.ghosteek_ai.llm.base import LLMCapabilities, LLMConfig
from bot.services.ghosteek_ai.llm.messages import (
    ChatMessage,
    LLMGenerateRequest,
    LLMGenerateResult,
    MessageRole,
)
from bot.services.ghosteek_ai.llm.response_parser import ResponseParser

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Контракт LLM-бэкенда: messages in → text / tool_calls out."""

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
        ...

    @abstractmethod
    async def stream_generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        ...

    @abstractmethod
    def supports_tools(self) -> bool:
        ...

    @abstractmethod
    def supports_stream(self) -> bool:
        ...

    @abstractmethod
    async def close(self) -> None:
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
            extra={
                k: v
                for k, v in kwargs.items()
                if k not in {"temperature", "max_tokens", "model"}
            },
        )


def ollama_config_from_settings() -> LLMConfig:
    from bot.config import settings

    return LLMConfig(
        provider="ollama",
        model=(settings.ollama_model or "llama3.2").strip(),
        base_url=(settings.ollama_url or "http://127.0.0.1:11434").rstrip("/"),
        temperature=0.3,
        max_tokens=1024,
        timeout_seconds=float(settings.ollama_timeout or 60.0),
        extra={"enable_tools": bool(getattr(settings, "ollama_enable_tools", True))},
    )


def qwen_config_from_settings() -> LLMConfig:
    """Конфиг OpenAI-compatible LLM из LLM_API_KEY / LLM_BASE_URL / LLM_MODEL."""
    from bot.config import settings

    return LLMConfig(
        provider="qwen",
        model=(settings.llm_model or "qwen3-235b-a22b-thinking-2507").strip(),
        base_url=(settings.llm_base_url or "").strip().rstrip("/"),
        api_key=(settings.llm_api_key or "").strip(),
        temperature=0.3,
        max_tokens=1024,
        timeout_seconds=float(getattr(settings, "llm_timeout", 90.0) or 90.0),
        extra={"enable_tools": True},
    )


def _role_value(role: MessageRole | str) -> str:
    return role.value if isinstance(role, MessageRole) else str(role)


def _messages_for_openai(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """OpenAI Chat Completions messages: system / user / assistant / tool."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = _role_value(msg.role).lower()
        content = msg.content if msg.content is not None else ""

        if role == "tool":
            entry: dict[str, Any] = {
                "role": "tool",
                "content": content,
            }
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.name:
                entry["name"] = msg.name
            out.append(entry)
            continue

        if role not in {"system", "user", "assistant"}:
            role = "user"

        entry = {"role": role, "content": content}
        if role == "assistant" and msg.tool_calls:
            entry["tool_calls"] = list(msg.tool_calls)
            # OpenAI допускает content=null / "" вместе с tool_calls
            if not (content or "").strip():
                entry["content"] = content if content is not None else ""
        out.append(entry)
    return out


def _messages_for_ollama(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Ollama /api/chat messages including tool / tool_calls."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = _role_value(msg.role).lower()
        content = msg.content if msg.content is not None else ""
        content_stripped = content.strip()

        if role == "tool":
            entry: dict[str, Any] = {
                "role": "tool",
                "content": content_stripped or content,
            }
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.name:
                entry["name"] = msg.name
            out.append(entry)
            continue

        if role not in {"system", "user", "assistant"}:
            role = "user"

        entry = {"role": role, "content": content_stripped}
        if role == "assistant" and msg.tool_calls:
            entry["tool_calls"] = list(msg.tool_calls)
            if not content_stripped:
                entry["content"] = ""
        if entry.get("content") or entry.get("tool_calls"):
            out.append(entry)
    return out


class OllamaProvider(LLMProvider):
    """Ollama REST POST /api/chat (aiohttp), с optional tool calling."""

    name = "ollama"

    def __init__(self, config: LLMConfig | None = None) -> None:
        cfg = config or ollama_config_from_settings()
        super().__init__(cfg)
        self._session: aiohttp.ClientSession | None = None
        self._parser = ResponseParser()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=float(self.config.timeout_seconds or 60.0))
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _chat_url(self) -> str:
        base = (self.config.base_url or "http://127.0.0.1:11434").rstrip("/")
        return f"{base}/api/chat"

    def _payload(
        self,
        req: LLMGenerateRequest,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        model = (req.model or self.config.model or "llama3.2").strip()
        body: dict[str, Any] = {
            "model": model,
            "messages": _messages_for_ollama(list(req.messages)),
            "stream": stream,
        }
        if req.tools and self.supports_tools():
            body["tools"] = list(req.tools)
        options: dict[str, Any] = {}
        if req.temperature is not None:
            options["temperature"] = float(req.temperature)
        if req.max_tokens is not None:
            options["num_predict"] = int(req.max_tokens)
        if options:
            body["options"] = options
        return body

    async def generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMGenerateResult:
        req = self._normalize_request(messages, tools=tools, **kwargs)
        url = self._chat_url()
        payload = self._payload(req, stream=False)
        session = await self._get_session()

        try:
            async with session.post(url, json=payload) as resp:
                raw_text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(
                        f"Ollama HTTP {resp.status} at {url}: {raw_text[:300]}"
                    )
                try:
                    data = json.loads(raw_text) if raw_text else {}
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"Ollama returned non-JSON response: {raw_text[:200]}"
                    ) from exc
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"Ollama connection error: {exc}") from exc

        parsed = self._parser.parse(data if isinstance(data, dict) else {})
        if not (parsed.text or "").strip() and not parsed.has_tool_calls:
            raise RuntimeError("Ollama returned empty message content")
        parsed.model = parsed.model or payload.get("model")
        return parsed

    async def stream_generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        req = self._normalize_request(messages, tools=tools, **kwargs)
        url = self._chat_url()
        payload = self._payload(req, stream=True)
        # streaming tool calls не используются в agent loop
        payload.pop("tools", None)
        session = await self._get_session()

        try:
            async with session.post(url, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Ollama HTTP {resp.status} at {url}: {body[:300]}"
                    )
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    message = chunk.get("message")
                    if isinstance(message, dict):
                        piece = message.get("content")
                        if isinstance(piece, str) and piece:
                            yield piece
                    alt = chunk.get("response")
                    if isinstance(alt, str) and alt and not isinstance(message, dict):
                        yield alt
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"Ollama stream connection error: {exc}") from exc

    def supports_tools(self) -> bool:
        return bool(self.config.extra.get("enable_tools", True))

    def supports_stream(self) -> bool:
        return True

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None


class QwenLLMProvider(LLMProvider):
    """OpenAI-compatible Chat Completions (Qwen / DashScope compatible-mode).

    Обычный HTTP (aiohttp). Без DashScope SDK.
    Streaming пока не реализован — только generate().
    """

    name = "qwen"

    def __init__(self, config: LLMConfig | None = None) -> None:
        cfg = config or qwen_config_from_settings()
        super().__init__(cfg)
        self._session: aiohttp.ClientSession | None = None
        self._parser = ResponseParser()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=float(self.config.timeout_seconds or 90.0))
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _chat_url(self) -> str:
        base = (self.config.base_url or "").strip().rstrip("/")
        if not base:
            raise RuntimeError(
                "LLM_BASE_URL is not configured. "
                "Set an OpenAI-compatible Chat Completions base URL."
            )
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        api_key = (self.config.api_key or "").strip()
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY is not configured. "
                "Set an API key for the OpenAI-compatible endpoint."
            )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        req: LLMGenerateRequest,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        model = (req.model or self.config.model or "qwen3-235b-a22b-thinking-2507").strip()
        body: dict[str, Any] = {
            "model": model,
            "messages": _messages_for_openai(list(req.messages)),
            "stream": bool(stream),
        }
        temperature = req.temperature if req.temperature is not None else self.config.temperature
        if temperature is not None:
            body["temperature"] = float(temperature)
        max_tokens = req.max_tokens if req.max_tokens is not None else self.config.max_tokens
        if max_tokens is not None:
            body["max_tokens"] = int(max_tokens)
        if req.tools and self.supports_tools():
            body["tools"] = list(req.tools)
        # response_format: из kwargs/extra или явного поля запроса
        response_format = None
        if isinstance(req.extra, dict):
            response_format = req.extra.get("response_format")
        if response_format is not None:
            body["response_format"] = response_format
        return body

    async def generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMGenerateResult:
        req = self._normalize_request(messages, tools=tools, **kwargs)
        # response_format может прийти kwargs'ом
        if "response_format" in kwargs and "response_format" not in req.extra:
            req.extra["response_format"] = kwargs["response_format"]

        url = self._chat_url()
        headers = self._headers()
        payload = self._payload(req, stream=False)
        session = await self._get_session()

        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                raw_text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(
                        f"Qwen/OpenAI HTTP {resp.status} at {url}: {raw_text[:400]}"
                    )
                try:
                    data = json.loads(raw_text) if raw_text else {}
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"Qwen/OpenAI returned non-JSON response: {raw_text[:200]}"
                    ) from exc
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"Qwen/OpenAI connection error: {exc}") from exc

        if not isinstance(data, dict):
            raise RuntimeError("Qwen/OpenAI returned unexpected payload type")

        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"Qwen/OpenAI API error: {msg}")

        parsed = self._parser.parse(data)
        if not (parsed.text or "").strip() and not parsed.has_tool_calls:
            raise RuntimeError("Qwen/OpenAI returned empty message content")
        parsed.model = parsed.model or payload.get("model")
        return parsed

    async def stream_generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming пока не реализован — используйте generate()."""
        self._normalize_request(messages, tools=tools, **kwargs)
        raise NotImplementedError(
            "QwenLLMProvider.stream_generate is not implemented yet. Use generate()."
        )
        if False:  # pragma: no cover
            yield ""

    def supports_tools(self) -> bool:
        return bool(self.config.extra.get("enable_tools", True))

    def supports_stream(self) -> bool:
        return False

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None


# Alias по ТЗ
QwenProvider = QwenLLMProvider


def get_llm_provider(name: str | None = None, *, config: LLMConfig | None = None) -> LLMProvider:
    key = (name or (config.provider if config else "") or "").strip().lower()
    if not key:
        from bot.config import settings

        key = (settings.ghosteek_ai_backend or "qwen").strip().lower()
    if key in {"qwen", "dashscope", "openai", "openai_compatible"}:
        return QwenLLMProvider(config or qwen_config_from_settings())
    if key in {"ollama", "local"}:
        return OllamaProvider(config or ollama_config_from_settings())
    if key in {"template", "default"}:
        # Factory/service не должны сюда попадать; безопасный fallback — ollama local
        return OllamaProvider(config or ollama_config_from_settings())
    return QwenLLMProvider(config or qwen_config_from_settings())

