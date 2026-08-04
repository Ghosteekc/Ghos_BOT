"""PromptBuilder — сборка messages для LLM без генерации текста."""

from __future__ import annotations

import json
from typing import Any

from bot.services.ghosteek_ai.constraints import CONSTRAINTS_SUMMARY
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.models import ToolResult
from bot.services.ghosteek_ai.voice import SYSTEM_PROMPT

# Лимиты TPM: короткая история + усечённые реплики.
_HISTORY_TURN_LIMIT = 6
_HISTORY_MSG_CHARS = 220
_SUMMARY_CHARS = 320
_TOOL_DATA_CHARS = 1200


class PromptBuilder:
    """Собирает prompt из блоков. Не генерирует ответ игроку.

    Порядок сообщений:
      1. System
      2. Planner recommendation (optional)
      3. Conversation history
      4. AIContext
      5. Tool Results (optional)
      6. User Message
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

    def build(
        self,
        ctx: AIContext,
        *,
        include_tool_results: bool = True,
        planner_recommendation: Any | None = None,
    ) -> list[ChatMessage]:
        """Полный список messages для LLMProvider.

        planner_recommendation — Plan (или объект с .intent/.tools): подсказка, не приказ.
        """
        messages: list[ChatMessage] = []
        messages.extend(self.build_system())
        messages.extend(self.build_planner_recommendation(planner_recommendation))
        messages.extend(self.build_conversation_history(ctx))
        messages.extend(self.build_ai_context(ctx))
        if include_tool_results:
            messages.extend(self.build_tool_results(ctx))
        messages.extend(self.build_user_message(ctx))
        return messages

    def build_planner_recommendation(self, plan: Any | None) -> list[ChatMessage]:
        if plan is None:
            return []
        intent = getattr(plan, "intent", None) or ""
        tools = getattr(plan, "tools", None) or []
        names: list[str] = []
        for t in tools:
            name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
            if name:
                names.append(str(name))
        if not intent and not names:
            return []
        # Коротко: без длинных пояснений про Agent Mode
        content = f"hint intent={intent or '—'}; tools={','.join(names) if names else '—'}"
        return [ChatMessage(role=MessageRole.SYSTEM, content=content)]

    def build_system(self) -> list[ChatMessage]:
        parts = [self.system_prompt.strip()]
        if self.constraints and self.constraints.strip():
            parts.append(self.constraints.strip())
        return [
            ChatMessage(role=MessageRole.SYSTEM, content="\n".join(parts)),
        ]

    def build_conversation_history(self, ctx: AIContext) -> list[ChatMessage]:
        out: list[ChatMessage] = []
        summary = (ctx.conversation_summary or "").strip()
        if summary:
            if len(summary) > _SUMMARY_CHARS:
                summary = summary[: _SUMMARY_CHARS - 1] + "…"
            out.append(
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=f"Summary: {summary}",
                )
            )

        turns = [
            turn
            for turn in (ctx.recent_messages or [])
            if isinstance(turn, dict) and str(turn.get("content") or "").strip()
        ]
        for turn in turns[-_HISTORY_TURN_LIMIT:]:
            role_raw = str(turn.get("role") or "").strip().lower()
            content = str(turn.get("content") or "").strip()
            if len(content) > _HISTORY_MSG_CHARS:
                content = content[: _HISTORY_MSG_CHARS - 1] + "…"
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
        payload = {k: v for k, v in payload.items() if k not in {"raw_message", "tool_outputs"}}
        if not payload:
            return []
        content = "Контекст:\n" + json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
        return [ChatMessage(role=MessageRole.SYSTEM, content=content)]

    def build_tool_results(self, ctx: AIContext) -> list[ChatMessage]:
        out: list[ChatMessage] = []
        outputs = ctx.tool_outputs or {}
        if not outputs:
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
                        content=self._compact_tool_content(tr),
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
                    content=self._compact_tool_content(tr),
                    name=tr.tool or str(tool_name),
                    tool_call_id=tr.call_id or f"call_{i}",
                )
            )
        return out

    @staticmethod
    def _compact_tool_content(tr: ToolResult) -> str:
        """Урезанный ToolResult для LLM: факты без тяжёлого envelope."""
        payload = {
            "tool": tr.tool,
            "ok": bool(tr.ok),
        }
        if tr.error_code:
            payload["error_code"] = tr.error_code
        if tr.error_params:
            payload["error_params"] = tr.error_params
        if tr.data:
            payload["data"] = tr.data
        if tr.actions:
            payload["actions"] = tr.actions[:3]
        text = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
        if len(text) > _TOOL_DATA_CHARS:
            return text[: _TOOL_DATA_CHARS - 1] + "…"
        return text

    def build_user_message(self, ctx: AIContext) -> list[ChatMessage]:
        text = (ctx.raw_message or "").strip()
        if not text:
            text = "(пустое сообщение пользователя)"
        return [ChatMessage(role=MessageRole.USER, content=text)]

    def build_openai_dicts(
        self,
        ctx: AIContext,
        *,
        include_tool_results: bool = True,
        planner_recommendation: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Тот же prompt в виде list[dict] для HTTP-клиентов."""
        return [
            m.to_dict()
            for m in self.build(
                ctx,
                include_tool_results=include_tool_results,
                planner_recommendation=planner_recommendation,
            )
        ]
