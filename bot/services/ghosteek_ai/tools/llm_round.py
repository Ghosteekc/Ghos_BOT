"""Multi-step LLM ↔ ToolCaller цикл.

Используется Agent Mode через ``run_llm_agent`` → ``execute_llm_round``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.llm.provider import LLMProvider
from bot.services.ghosteek_ai.models import ToolResult

logger = logging.getLogger(__name__)

MAX_LLM_ROUND_ITERATIONS = 5
_ROUND_TOOL_NAME = "execute_llm_round"


@dataclass
class LLMRoundResult:
    """Итог цикла LLM → tools → messages → LLM.

    При ошибке ``ok=False`` и ``error`` — ToolResult (исключения наружу не летят).
    """

    ok: bool
    text: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    iterations: int = 0
    used_tools: bool = False
    error: ToolResult | None = None

    def to_error_result(self) -> ToolResult:
        """Удобный доступ к envelope ошибки (или синтетический ok-результат)."""
        if self.error is not None:
            return self.error
        return ToolResult(
            tool=_ROUND_TOOL_NAME,
            ok=self.ok,
            data={
                "text": self.text,
                "iterations": self.iterations,
                "used_tools": self.used_tools,
                "tool_names": [r.tool for r in self.tool_results],
            },
        )


def _error_result(
    code: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        tool=_ROUND_TOOL_NAME,
        ok=False,
        error_code=code,
        error_params=dict(params or {}),
        data=dict(data or {}),
    ).normalized()


def _append_assistant_tool_calls(messages: list[ChatMessage], result) -> None:
    assistant_tool_calls = [tc.to_dict() for tc in result.tool_calls]
    messages.append(
        ChatMessage(
            role=MessageRole.ASSISTANT,
            content=(result.text or "").strip(),
            tool_calls=assistant_tool_calls,
        )
    )


def _append_tool_messages(
    messages: list[ChatMessage],
    *,
    llm_tool_calls,
    results: list[ToolResult],
) -> None:
    for i, tr in enumerate(results):
        call_id = ""
        if i < len(llm_tool_calls):
            call_id = llm_tool_calls[i].id
        call_id = call_id or tr.call_id or f"call_{i}"
        messages.append(
            ChatMessage(
                role=MessageRole.TOOL,
                content=tr.normalized(call_id=call_id).to_llm_content(),
                name=tr.tool,
                tool_call_id=call_id,
            )
        )


async def execute_llm_round(
    messages: list[ChatMessage],
    ctx: AIContext,
    *,
    provider: LLMProvider,
    caller: "ToolCaller",
    tools: list[dict[str, Any]] | None = None,
    max_iterations: int = MAX_LLM_ROUND_ITERATIONS,
) -> LLMRoundResult:
    """Цикл: LLM → tool_calls → ToolCaller → ToolResult → messages → LLM …

    - Максимум ``max_iterations`` (потолок 5) вызовов модели.
    - Нет tool_calls → цикл завершается, текст ответа модели = финал.
    - Любая ошибка → ``LLMRoundResult(ok=False, error=ToolResult(...))``, без raise.
    """
    from bot.services.ghosteek_ai.tools.base import ToolCaller

    if not isinstance(caller, ToolCaller):
        err = _error_result("LLM_ROUND_INVALID_CALLER")
        return LLMRoundResult(ok=False, messages=list(messages), error=err)

    working = list(messages)
    all_results: list[ToolResult] = []
    used_tools = False
    iterations = 0
    limit = max(1, min(int(max_iterations), MAX_LLM_ROUND_ITERATIONS))

    try:
        if not provider.supports_tools():
            err = _error_result(
                "LLM_ROUND_TOOLS_UNSUPPORTED",
                params={"provider": getattr(provider, "name", type(provider).__name__)},
            )
            return LLMRoundResult(ok=False, messages=working, error=err)

        tools_schema = tools if tools is not None else caller.registry.openai_tools()
        if not tools_schema:
            err = _error_result("LLM_ROUND_NO_TOOLS")
            return LLMRoundResult(ok=False, messages=working, error=err)

        for round_idx in range(limit):
            iterations = round_idx + 1
            try:
                llm_result = await provider.generate(working, tools=tools_schema)
            except Exception as exc:
                logger.exception("execute_llm_round: provider.generate failed")
                err = _error_result(
                    "LLM_ROUND_PROVIDER_ERROR",
                    params={"error": str(exc)[:400]},
                    data={"iterations": iterations, "used_tools": used_tools},
                )
                return LLMRoundResult(
                    ok=False,
                    messages=working,
                    tool_results=all_results,
                    iterations=iterations,
                    used_tools=used_tools,
                    error=err,
                )

            if not llm_result.has_tool_calls:
                return LLMRoundResult(
                    ok=True,
                    text=(llm_result.text or "").strip(),
                    messages=working,
                    tool_results=all_results,
                    iterations=iterations,
                    used_tools=used_tools,
                )

            used_tools = True
            _append_assistant_tool_calls(working, llm_result)

            try:
                raw_calls = [tc.to_dict() for tc in llm_result.tool_calls]
                round_results = await caller.execute_qwen_tool_calls(raw_calls, ctx)
            except Exception as exc:
                logger.exception("execute_llm_round: tool execution failed")
                err = _error_result(
                    "LLM_ROUND_TOOL_ERROR",
                    params={"error": str(exc)[:400]},
                    data={"iterations": iterations, "used_tools": used_tools},
                )
                return LLMRoundResult(
                    ok=False,
                    messages=working,
                    tool_results=all_results,
                    iterations=iterations,
                    used_tools=used_tools,
                    error=err,
                )

            all_results.extend(round_results)
            _append_tool_messages(
                working,
                llm_tool_calls=llm_result.tool_calls,
                results=round_results,
            )
            logger.info(
                "execute_llm_round iteration=%s tools=%s",
                iterations,
                [r.tool for r in round_results],
            )

        # Исчерпан лимит, модель всё ещё запрашивала tools.
        err = _error_result(
            "LLM_ROUND_MAX_ITERATIONS",
            params={"max_iterations": limit},
            data={
                "iterations": iterations,
                "used_tools": used_tools,
                "tool_names": [r.tool for r in all_results],
            },
        )
        return LLMRoundResult(
            ok=False,
            messages=working,
            tool_results=all_results,
            iterations=iterations,
            used_tools=used_tools,
            error=err,
        )
    except Exception as exc:
        logger.exception("execute_llm_round: unexpected failure")
        err = _error_result(
            "LLM_ROUND_ERROR",
            params={"error": str(exc)[:400]},
            data={"iterations": iterations, "used_tools": used_tools},
        )
        return LLMRoundResult(
            ok=False,
            messages=working,
            tool_results=all_results,
            iterations=iterations,
            used_tools=used_tools,
            error=err,
        )
