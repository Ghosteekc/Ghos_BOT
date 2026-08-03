"""Разбор сырого ответа LLM → текст / tool_calls (без вызова модели)."""

from __future__ import annotations

import json
from typing import Any

from bot.services.ghosteek_ai.llm.messages import LLMGenerateResult, LLMToolCall


class ResponseParser:
    """Парсит ответ провайдера в LLMGenerateResult.

    Не генерирует текст и не вызывает tools — только нормализация структуры.
    """

    def parse(self, raw: Any) -> LLMGenerateResult:
        if isinstance(raw, LLMGenerateResult):
            return raw
        if isinstance(raw, str):
            return LLMGenerateResult(text=raw.strip(), raw={"text": raw})
        if not isinstance(raw, dict):
            return LLMGenerateResult(text=str(raw or ""), raw={"value": raw})

        # OpenAI / Qwen chat.completion shape
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            return self._parse_openai_choice(raw, choices[0])

        # Ollama /api/chat shape
        if "message" in raw and isinstance(raw.get("message"), dict):
            return self._parse_ollama_message(raw)

        # Уже нормализованный dict
        if "text" in raw or "tool_calls" in raw:
            return LLMGenerateResult(
                text=str(raw.get("text") or "").strip(),
                tool_calls=self._parse_tool_calls(raw.get("tool_calls")),
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
        text = self._coerce_content(message.get("content"))
        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        return LLMGenerateResult(
            text=text,
            tool_calls=tool_calls,
            raw=dict(raw),
            finish_reason=choice.get("finish_reason"),
            model=raw.get("model"),
        )

    def _parse_ollama_message(self, raw: dict[str, Any]) -> LLMGenerateResult:
        message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
        text = self._coerce_content(message.get("content"))
        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        return LLMGenerateResult(
            text=text,
            tool_calls=tool_calls,
            raw=dict(raw),
            finish_reason=raw.get("done_reason") or ("stop" if raw.get("done") else None),
            model=raw.get("model"),
        )

    @staticmethod
    def _coerce_content(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(str(item.get("text") or ""))
                    elif "text" in item:
                        parts.append(str(item.get("text") or ""))
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
