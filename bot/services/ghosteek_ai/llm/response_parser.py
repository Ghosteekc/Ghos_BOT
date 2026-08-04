"""Разбор сырого ответа LLM → текст / tool_calls / reasoning (без вызова модели)."""

from __future__ import annotations

import json
from typing import Any

from bot.services.ghosteek_ai.llm.messages import LLMGenerateResult, LLMToolCall


class ResponseParser:
    """Парсит ответ провайдера в LLMGenerateResult.

    Поддерживает OpenAI Chat Completions, Groq (reasoning / tool_calls), Ollama.
    Не генерирует текст и не вызывает tools — только нормализация структуры.
    """

    def parse(self, raw: Any) -> LLMGenerateResult:
        if isinstance(raw, LLMGenerateResult):
            return raw
        if isinstance(raw, str):
            return LLMGenerateResult(text=raw.strip(), raw={"text": raw})
        if not isinstance(raw, dict):
            return LLMGenerateResult(text=str(raw or ""), raw={"value": raw})

        # OpenAI / Qwen / Groq chat.completion shape
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            return self._parse_openai_choice(raw, choices[0])

        # Ollama /api/chat shape
        if "message" in raw and isinstance(raw.get("message"), dict):
            return self._parse_ollama_message(raw)

        # Уже нормализованный dict
        if "text" in raw or "tool_calls" in raw or "reasoning" in raw:
            reasoning = self._coerce_content(
                raw.get("reasoning") or raw.get("reasoning_content")
            )
            text = str(raw.get("text") or "").strip()
            tool_calls = self._parse_tool_calls(raw.get("tool_calls"))
            # reasoning НЕ копируем в text — это не ответ игроку
            return LLMGenerateResult(
                text=text,
                tool_calls=tool_calls,
                reasoning=reasoning,
                raw=dict(raw),
                finish_reason=raw.get("finish_reason"),
                model=raw.get("model"),
            )

        return LLMGenerateResult(text="", raw=dict(raw))

    def extract_text(self, raw: Any) -> str:
        return self.parse(raw).text

    def extract_tool_calls(self, raw: Any) -> list[LLMToolCall]:
        return list(self.parse(raw).tool_calls)

    def _parse_openai_choice(
        self, raw: dict[str, Any], choice: Any
    ) -> LLMGenerateResult:
        if not isinstance(choice, dict):
            return LLMGenerateResult(raw=dict(raw))

        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        # delta — на случай stream-like / incomplete payloads
        if not message and isinstance(choice.get("delta"), dict):
            message = choice["delta"]

        content_text = self._coerce_content(message.get("content"))
        reasoning = self._extract_reasoning(message, choice, raw)
        tool_calls = self._parse_tool_calls(
            message.get("tool_calls") or choice.get("tool_calls")
        )

        # content и reasoning разделены: reasoning никогда не становится text
        return LLMGenerateResult(
            text=content_text,
            tool_calls=tool_calls,
            reasoning=reasoning,
            raw=dict(raw),
            finish_reason=choice.get("finish_reason") or raw.get("finish_reason"),
            model=raw.get("model"),
        )

    def _parse_ollama_message(self, raw: dict[str, Any]) -> LLMGenerateResult:
        message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
        content_text = self._coerce_content(message.get("content"))
        reasoning = self._extract_reasoning(message, {}, raw)
        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        return LLMGenerateResult(
            text=content_text,
            tool_calls=tool_calls,
            reasoning=reasoning,
            raw=dict(raw),
            finish_reason=raw.get("done_reason") or ("stop" if raw.get("done") else None),
            model=raw.get("model"),
        )

    def _extract_reasoning(
        self,
        message: dict[str, Any],
        choice: dict[str, Any],
        raw: dict[str, Any],
    ) -> str:
        for source in (message, choice, raw):
            if not isinstance(source, dict):
                continue
            for key in (
                "reasoning",
                "reasoning_content",
                "reasoning_text",
                "thinking",
            ):
                value = self._coerce_content(source.get(key))
                if value:
                    return value
        return ""

    @staticmethod
    def _coerce_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    item_type = str(item.get("type") or "")
                    if item_type in {"text", "output_text", "input_text"}:
                        parts.append(str(item.get("text") or ""))
                    elif item_type in {"reasoning", "thinking"}:
                        parts.append(
                            str(
                                item.get("text")
                                or item.get("reasoning")
                                or item.get("content")
                                or ""
                            )
                        )
                    elif "text" in item:
                        parts.append(str(item.get("text") or ""))
                    elif "content" in item and isinstance(item.get("content"), str):
                        parts.append(item["content"])
            return "".join(parts).strip()
        return ""

    def _parse_tool_calls(self, raw_calls: Any) -> list[LLMToolCall]:
        if not isinstance(raw_calls, list):
            return []
        out: list[LLMToolCall] = []
        for i, item in enumerate(raw_calls):
            if not isinstance(item, dict):
                continue
            fn = item.get("function") if isinstance(item.get("function"), dict) else {}
            name = str(fn.get("name") or item.get("name") or "")
            if not name:
                continue
            args_raw = fn.get("arguments", item.get("arguments", {}))
            arguments = self._coerce_arguments(args_raw)
            call_id = str(item.get("id") or f"call_{i}")
            out.append(LLMToolCall(id=call_id, name=name, arguments=arguments))
        return out

    @staticmethod
    def _coerce_arguments(args_raw: Any) -> dict[str, Any]:
        if isinstance(args_raw, dict):
            return dict(args_raw)
        if isinstance(args_raw, str):
            text = args_raw.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {"_raw": text}
            return dict(parsed) if isinstance(parsed, dict) else {"_raw": parsed}
        return {}
