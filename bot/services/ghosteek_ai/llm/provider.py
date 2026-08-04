"""Ollama / Qwen message encoding helpers and LLMProvider implementations."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from bot.services.ghosteek_ai.llm.base import LLMCapabilities, LLMConfig, ProviderError
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
    """Конфиг OpenAI-compatible LLM (Qwen / Groq / DashScope) из LLM_*."""
    from bot.config import settings

    base_url = (settings.llm_base_url or "").strip().rstrip("/")
    backend = (settings.ghosteek_ai_backend or "").strip().lower()
    provider_name = "qwen"
    if backend == "groq" or "groq.com" in base_url.lower():
        provider_name = "groq"

    return LLMConfig(
        provider=provider_name,
        model=(settings.llm_model or "qwen3-235b-a22b-thinking-2507").strip(),
        base_url=base_url,
        api_key=(settings.llm_api_key or "").strip(),
        temperature=0.3,
        max_tokens=1024,
        timeout_seconds=float(getattr(settings, "llm_timeout", 90.0) or 90.0),
        extra={
            "enable_tools": True,
            # Groq reasoning models: отдельное поле message.reasoning
            "reasoning_format": "parsed" if provider_name == "groq" else None,
        },
    )


def _role_value(role: MessageRole | str) -> str:
    return role.value if isinstance(role, MessageRole) else str(role)


def _messages_for_openai(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """OpenAI / Groq Chat Completions messages: system / user / assistant / tool."""
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

        entry: dict[str, Any] = {"role": role, "content": content}
        if role == "assistant" and msg.tool_calls:
            entry["tool_calls"] = list(msg.tool_calls)
            # OpenAI/Groq: content может быть "" / null вместе с tool_calls
            if not (content or "").strip():
                entry["content"] = content if content is not None else ""
        # Groq multi-turn: reasoning нужно возвращать модели
        if role == "assistant" and getattr(msg, "reasoning", None):
            entry["reasoning"] = msg.reasoning
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
        self._parser = ResponseParser()

    def _client_timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=float(self.config.timeout_seconds or 60.0))

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

        try:
            async with aiohttp.ClientSession(timeout=self._client_timeout()) as session:
                async with session.post(url, json=payload) as resp:
                    raw_text = await resp.text()
                    if resp.status >= 400:
                        raise ProviderError(
                            f"Ollama HTTP {resp.status} at {url}: {raw_text[:300]}",
                            code="OLLAMA_HTTP_ERROR",
                            details={"status": resp.status, "body": raw_text[:2000]},
                        )
                    try:
                        data = json.loads(raw_text) if raw_text else {}
                    except json.JSONDecodeError as exc:
                        raise ProviderError(
                            f"Ollama returned non-JSON response: {raw_text[:200]}",
                            code="OLLAMA_NON_JSON",
                        ) from exc
        except ProviderError:
            raise
        except aiohttp.ClientError as exc:
            raise ProviderError(
                f"Ollama connection error: {exc}",
                code="OLLAMA_CONNECTION_ERROR",
            ) from exc

        parsed = self._parser.parse(data if isinstance(data, dict) else {})
        # reasoning ≠ ответ игроку; usable = content | tools | reasoning (для retry)
        if not (
            parsed.has_tool_calls
            or (parsed.text or "").strip()
            or (parsed.reasoning or "").strip()
        ):
            raise ProviderError(
                "Ollama returned empty message content",
                code="OLLAMA_EMPTY_CONTENT",
            )
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
        payload.pop("tools", None)

        try:
            async with aiohttp.ClientSession(timeout=self._client_timeout()) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        raise ProviderError(
                            f"Ollama HTTP {resp.status} at {url}: {body[:300]}",
                            code="OLLAMA_HTTP_ERROR",
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
        except ProviderError:
            raise
        except aiohttp.ClientError as exc:
            raise ProviderError(
                f"Ollama stream connection error: {exc}",
                code="OLLAMA_CONNECTION_ERROR",
            ) from exc

    def supports_tools(self) -> bool:
        return bool(self.config.extra.get("enable_tools", True))

    def supports_stream(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class QwenLLMProvider(LLMProvider):
    """OpenAI-compatible Chat Completions (Qwen / Groq / DashScope).

    Endpoint: ``{LLM_BASE_URL}/chat/completions`` (не Responses API).
    HTTP через aiohttp. Streaming пока не реализован.
    """

    name = "qwen"

    def __init__(self, config: LLMConfig | None = None) -> None:
        cfg = config or qwen_config_from_settings()
        super().__init__(cfg)
        # name отражает фактический бэкенд (qwen / groq)
        self.name = (cfg.provider or "qwen").strip().lower() or "qwen"
        self._parser = ResponseParser()

    def _is_groq(self) -> bool:
        if self.name == "groq":
            return True
        base = (self.config.base_url or "").lower()
        return "groq.com" in base

    def _client_timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=float(self.config.timeout_seconds or 90.0))

    def _chat_url(self) -> str:
        base = (self.config.base_url or "").strip().rstrip("/")
        if not base:
            raise ProviderError(
                "LLM_BASE_URL is not configured. "
                "Set an OpenAI-compatible Chat Completions base URL "
                "(e.g. https://api.groq.com/openai/v1).",
                code="LLM_BASE_URL_MISSING",
            )
        # Уже полный path
        if base.endswith("/chat/completions"):
            return base
        # Groq / OpenAI-compatible: Chat Completions, не Responses API
        return f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        api_key = (self.config.api_key or "").strip()
        if not api_key:
            raise ProviderError(
                "LLM_API_KEY is not configured.",
                code="LLM_API_KEY_MISSING",
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
        default_model = (
            "llama-3.3-70b-versatile"
            if self._is_groq()
            else "qwen3-235b-a22b-thinking-2507"
        )
        model = (req.model or self.config.model or default_model).strip()
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

        response_format = None
        reasoning_format = None
        if isinstance(req.extra, dict):
            response_format = req.extra.get("response_format")
            reasoning_format = req.extra.get("reasoning_format")
        if response_format is not None:
            body["response_format"] = response_format
        # Groq reasoning models: message.reasoning при reasoning_format=parsed
        if reasoning_format is None and self._is_groq():
            reasoning_format = self.config.extra.get("reasoning_format") or "parsed"
        if reasoning_format:
            body["reasoning_format"] = reasoning_format
        return body

    def _log_raw_response(
        self,
        *,
        url: str,
        status: int,
        headers: Any,
        raw_text: str,
        data: Any,
    ) -> None:
        """Полный debug dump ответа до интерпретации (без усечения JSON)."""
        try:
            header_map = {
                k: v
                for k, v in (headers.items() if headers is not None else [])
                if str(k).lower() not in {"authorization", "cookie", "set-cookie"}
            }
        except Exception:
            header_map = {}
        if isinstance(data, (dict, list)):
            body_dump = json.dumps(data, ensure_ascii=False, default=str)
        else:
            body_dump = raw_text if raw_text is not None else str(data)
        logger.debug(
            "llm_provider_raw_response provider=%s url=%s status=%s headers=%s body=%s",
            self.name,
            url,
            status,
            json.dumps(header_map, ensure_ascii=False, default=str),
            body_dump,
        )

    async def generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMGenerateResult:
        req = self._normalize_request(messages, tools=tools, **kwargs)
        if "response_format" in kwargs and "response_format" not in req.extra:
            req.extra["response_format"] = kwargs["response_format"]
        if "reasoning_format" in kwargs and "reasoning_format" not in req.extra:
            req.extra["reasoning_format"] = kwargs["reasoning_format"]

        try:
            url = self._chat_url()
            headers = self._headers()
            payload = self._payload(req, stream=False)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"Failed to build LLM request: {exc}",
                code="LLM_REQUEST_BUILD_ERROR",
                details={"error": str(exc)[:400]},
            ) from exc

        raw_text = ""
        status = 0
        resp_headers: Any = None
        data: Any = None

        try:
            # Per-request session: гарантированно закрывается (нет Unclosed client session)
            async with aiohttp.ClientSession(timeout=self._client_timeout()) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    status = int(resp.status)
                    resp_headers = resp.headers
                    raw_text = await resp.text()
                    try:
                        data = json.loads(raw_text) if raw_text else {}
                    except json.JSONDecodeError:
                        data = None

                    self._log_raw_response(
                        url=url,
                        status=status,
                        headers=resp_headers,
                        raw_text=raw_text,
                        data=data if data is not None else raw_text,
                    )

                    if status >= 400:
                        raise ProviderError(
                            f"LLM HTTP {status} at {url}: {(raw_text or '')[:500]}",
                            code="LLM_HTTP_ERROR",
                            details={"status": status, "url": url, "body": (raw_text or "")[:2000]},
                        )
        except ProviderError:
            raise
        except aiohttp.ClientError as exc:
            raise ProviderError(
                f"LLM connection error: {exc}",
                code="LLM_CONNECTION_ERROR",
                details={"url": url, "error": str(exc)[:400]},
            ) from exc
        except Exception as exc:
            raise ProviderError(
                f"LLM request failed: {exc}",
                code="LLM_REQUEST_ERROR",
                details={"url": url, "error": str(exc)[:400]},
            ) from exc

        if data is None:
            raise ProviderError(
                f"LLM returned non-JSON response: {(raw_text or '')[:300]}",
                code="LLM_NON_JSON",
                details={"status": status, "body": (raw_text or "")[:2000]},
            )
        if not isinstance(data, dict):
            raise ProviderError(
                "LLM returned unexpected payload type",
                code="LLM_BAD_PAYLOAD",
                details={"type": type(data).__name__},
            )

        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise ProviderError(
                f"LLM API error: {msg}",
                code="LLM_API_ERROR",
                details={"error": err},
            )

        parsed = self._parser.parse(data)
        # content / tool_calls / reasoning разделены.
        # reasoning НИКОГДА не копируется в text (не для пользователя).
        if parsed.has_tool_calls:
            parsed.model = parsed.model or payload.get("model")
            return parsed

        if (parsed.text or "").strip() or (parsed.reasoning or "").strip():
            parsed.model = parsed.model or payload.get("model")
            return parsed

        raise ProviderError(
            "LLM returned empty message content "
            "(no content, no tool_calls, no reasoning)",
            code="LLM_EMPTY_CONTENT",
            details={
                "finish_reason": parsed.finish_reason,
                "model": parsed.model or payload.get("model"),
                "has_choices": bool(isinstance(data.get("choices"), list) and data.get("choices")),
                "usage": data.get("usage"),
            },
        )

    async def stream_generate(
        self,
        messages: list[ChatMessage] | LLMGenerateRequest,
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming пока не реализован — используйте generate()."""
        self._normalize_request(messages, tools=tools, **kwargs)
        raise ProviderError(
            "stream_generate is not implemented. Use generate().",
            code="LLM_STREAM_NOT_IMPLEMENTED",
        )
        if False:  # pragma: no cover
            yield ""

    def supports_tools(self) -> bool:
        return bool(self.config.extra.get("enable_tools", True))

    def supports_stream(self) -> bool:
        return False

    async def close(self) -> None:
        # Per-request sessions — нечего закрывать; метод для контракта LLMProvider.
        return None


# Alias по ТЗ
QwenProvider = QwenLLMProvider
GroqProvider = QwenLLMProvider


def get_llm_provider(name: str | None = None, *, config: LLMConfig | None = None) -> LLMProvider:
    key = (name or (config.provider if config else "") or "").strip().lower()
    if not key:
        from bot.config import settings

        key = (settings.ghosteek_ai_backend or "qwen").strip().lower()
    if key in {"qwen", "dashscope", "openai", "openai_compatible", "groq"}:
        cfg = config or qwen_config_from_settings()
        if key == "groq" and cfg.provider != "groq":
            cfg = LLMConfig(
                provider="groq",
                model=cfg.model,
                base_url=cfg.base_url,
                api_key=cfg.api_key,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                timeout_seconds=cfg.timeout_seconds,
                extra={**dict(cfg.extra), "reasoning_format": cfg.extra.get("reasoning_format") or "parsed"},
            )
        return QwenLLMProvider(cfg)
    if key in {"ollama", "local"}:
        return OllamaProvider(config or ollama_config_from_settings())
    if key in {"template", "default"}:
        return OllamaProvider(config or ollama_config_from_settings())
    return QwenLLMProvider(config or qwen_config_from_settings())

