"""PromptBuilder — сборка messages для LLM без генерации текста."""

from __future__ import annotations

import json
from typing import Any

from bot.services.ghosteek_ai.constraints import CONSTRAINTS_SUMMARY
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.voice import SYSTEM_PROMPT


class PromptBuilder:
    """Собирает prompt из блоков. Не генерирует ответ игроку.

    Порядок сообщений:
      1. System
      2. Conversation history
      3. AIContext
      4. Tool Results
      5. User Message
    """

    def __init__(
        self,
        *,
        system_prompt: str | None = None,
        constraints: str | None = None,
    ) -> None:
        self.system_prompt = system_prompt if system_prompt is not None else SYSTEM_PROMPT
        self.constraints = (
            constraints if constraints is not None else CONSTRAINTS_SUMMARY
        )

    def build(self, ctx: AIContext) -> list[ChatMessage]:
        """Полный список messages для LLMProvider."""
        messages: list[ChatMessage] = []
        messages.extend(self.build_system())
        messages.extend(self.build_conversation_history(ctx))
        messages.extend(self.build_ai_context(ctx))
        messages.extend(self.build_tool_results(ctx))
        messages.extend(self.build_user_message(ctx))
        return messages

    def build_system(self) -> list[ChatMessage]:
        parts = [self.system_prompt.strip()]
        if self.constraints and self.constraints.strip():
            parts.append(f"Ограничения данных:\n{self.constraints.strip()}")
        return [
            ChatMessage(role=MessageRole.SYSTEM, content="\n\n".join(parts)),
        ]

    def build_conversation_history(self, ctx: AIContext) -> list[ChatMessage]:
        out: list[ChatMessage] = []
        summary = (ctx.conversation_summary or "").strip()
        if summary:
            out.append(
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=f"Краткое summary диалога:\n{summary}",
                )
            )

        for turn in ctx.recent_messages or []:
            if not isinstance(turn, dict):
                continue
            role_raw = str(turn.get("role") or "").strip().lower()
            content = str(turn.get("content") or "").strip()
            if not content:
                continue
            if role_raw in {"assistant", "ai", "bot", "coach"}:
                role: MessageRole | str = MessageRole.ASSISTANT
            elif role_raw in {"system"}:
                role = MessageRole.SYSTEM
            else:
                role = MessageRole.USER
            out.append(ChatMessage(role=role, content=content))
        return out

    def build_ai_context(self, ctx: AIContext) -> list[ChatMessage]:
        payload = ctx.to_llm_dict()
        # raw_message уже уйдёт отдельным user-блоком — убираем дубль из JSON
        payload = {k: v for k, v in payload.items() if k != "raw_message"}
        # tool_outputs дублируются в Tool Results-блоке
        payload = {k: v for k, v in payload.items() if k != "tool_outputs"}
        content = (
            "AIContext (structured JSON, опирайся только на эти данные):\n"
            + json.dumps(payload, ensure_ascii=False, default=str)
        )
        return [ChatMessage(role=MessageRole.SYSTEM, content=content)]

    def build_tool_results(self, ctx: AIContext) -> list[ChatMessage]:
        out: list[ChatMessage] = []
        outputs = ctx.tool_outputs or {}
        if not outputs:
            # fallback: primary data как один tool-результат
            if ctx.data or ctx.error_code is not None:
                tr = ToolResult(
                    tool=ctx.service or "primary",
                    ok=bool(ctx.ok),
                    data=dict(ctx.data or {}),
                    error_code=ctx.error_code,
                    error_params=dict(ctx.error_params or {}),
                    actions=[dict(a) for a in (ctx.actions or []) if isinstance(a, dict)],
                    call_id="call_primary",
                )
                out.append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=tr.to_llm_content(),
                        name=tr.tool,
                        tool_call_id=tr.call_id,
                    )
                )
            return out

        for i, (tool_name, raw) in enumerate(outputs.items()):
            if not isinstance(raw, dict):
                continue
            payload = dict(raw)
            if "tool" not in payload:
                payload["tool"] = tool_name
            tr = ToolResult.from_dict(payload).normalized(
                call_id=str(payload.get("call_id") or f"call_{i}")
            )
            out.append(
                ChatMessage(
                    role=MessageRole.TOOL,
                    content=tr.to_llm_content(),
                    name=tr.tool or str(tool_name),
                    tool_call_id=tr.call_id or f"call_{i}",
                )
            )
        return out

    def build_user_message(self, ctx: AIContext) -> list[ChatMessage]:
        text = (ctx.raw_message or "").strip()
        if not text:
            text = "(пустое сообщение пользователя)"
        return [ChatMessage(role=MessageRole.USER, content=text)]

    def build_openai_dicts(self, ctx: AIContext) -> list[dict[str, Any]]:
        """Тот же prompt в виде list[dict] для HTTP-клиентов."""
        return [m.to_dict() for m in self.build(ctx)]
