"""Multi-step LLM ↔ ToolCaller цикл.

Используется Agent Mode через ``run_llm_agent`` → ``execute_llm_round``.

Правило Agent Mode: финальный текст только поверх успешного ToolResult.
Без tool / tool ok=False → ответ блокируется.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.llm.provider import LLMProvider
from bot.services.ghosteek_ai.llm.reasoning_filter import (
    FINAL_ANSWER_RETRY_PROMPT,
    DEFAULT_REASONING_FILTER,
    finalize_user_facing_text,
)
from bot.services.ghosteek_ai.models import ToolResult

logger = logging.getLogger(__name__)

MAX_LLM_ROUND_ITERATIONS = 5
_ROUND_TOOL_NAME = "execute_llm_round"

# Фиксированный отказ — LLM не имеет права отвечать без успешного tool.
NO_DATA_USER_MESSAGE = "Не удалось получить данные."
FORCE_TOOL_USER_PROMPT = (
    "Сначала вызови нужный tool. "
    "Нельзя давать финальный ответ игроку без успешного результата tool."
)

# Stubs / служебные — не считаются источником фактов для ответа.
_NON_FACT_TOOLS = frozenset({_ROUND_TOOL_NAME})


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


def successful_tool_results(results: list[ToolResult]) -> list[ToolResult]:
    """ToolResult, на которых разрешено писать финальный ответ."""
    return [
        r for r in results
        if r.ok and r.tool not in _NON_FACT_TOOLS
    ]


def has_successful_tool_result(results: list[ToolResult]) -> bool:
    return bool(successful_tool_results(results))


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


def _blocked_no_tool(
    *,
    code: str,
    working: list[ChatMessage],
    all_results: list[ToolResult],
    iterations: int,
    used_tools: bool,
    detail: str = "",
) -> LLMRoundResult:
    """Блок финального ответа: нет успешного ToolResult."""
    params: dict[str, Any] = {"user_message": NO_DATA_USER_MESSAGE}
    if detail:
        params["detail"] = detail[:400]
    err = _error_result(
        code,
        params=params,
        data={
            "iterations": iterations,
            "used_tools": used_tools,
            "tool_names": [r.tool for r in all_results],
            "successful_tools": [r.tool for r in successful_tool_results(all_results)],
        },
    )
    logger.info(
        "execute_llm_round blocked code=%s iterations=%s used_tools=%s tools=%s",
        code,
        iterations,
        used_tools,
        [r.tool for r in all_results],
    )
    return LLMRoundResult(
        ok=False,
        text="",
        messages=working,
        tool_results=all_results,
        iterations=iterations,
        used_tools=used_tools,
        error=err,
    )


def _append_assistant_tool_calls(messages: list[ChatMessage], result) -> None:
    assistant_tool_calls = [tc.to_dict() for tc in result.tool_calls]
    reasoning = getattr(result, "reasoning", None) or ""
    messages.append(
        ChatMessage(
            role=MessageRole.ASSISTANT,
            content=(result.text or "").strip(),
            tool_calls=assistant_tool_calls,
            reasoning=reasoning.strip() or None,
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


def _facts_blob(results: list[ToolResult]) -> str:
    """Сериализованные факты успешных tools для мягкой сверки ответа."""
    parts: list[str] = []
    for r in successful_tool_results(results):
        try:
            parts.append(json.dumps(r.to_dict(), ensure_ascii=False))
        except Exception:
            parts.append(str(r.data))
    return "\n".join(parts).lower()


def _answer_grounded_in_tools(text: str, results: list[ToolResult]) -> bool:
    """Грубая проверка: ответ не пустой и есть успешный ToolResult.

    Полный semantic fact-lock не делаем (без изменения API); без успешного
    tool финал уже запрещён. Здесь отсекаем пустые/служебные ответы.
    """
    if not has_successful_tool_result(results):
        return False
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return bool(_facts_blob(results).strip())


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
    - Финальный текст разрешён только если есть успешный ToolResult.
    - Нет tool / tool failed → ``ok=False``, код LLM_ROUND_NO_SUCCESSFUL_TOOL.
    """
    from bot.services.ghosteek_ai.tools.base import ToolCaller

    # ctx обновляется внутри ToolCaller при execute_qwen_tool_calls.
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
                final = finalize_user_facing_text(
                    content=llm_result.text,
                    reasoning=getattr(llm_result, "reasoning", None),
                    filter=DEFAULT_REASONING_FILTER,
                )

                # --- Gate: без успешного ToolResult финал запрещён ---
                if not has_successful_tool_result(all_results):
                    if used_tools:
                        # Tools вызывались, но все упали — не даём модели «додумать».
                        return _blocked_no_tool(
                            code="LLM_ROUND_TOOL_FAILED",
                            working=working,
                            all_results=all_results,
                            iterations=iterations,
                            used_tools=used_tools,
                            detail="all tool calls failed",
                        )
                    # Ещё не было tools — просим вызвать tool (если есть слоты).
                    logger.info(
                        "execute_llm_round: block final without tools iteration=%s",
                        iterations,
                    )
                    working.append(
                        ChatMessage(
                            role=MessageRole.ASSISTANT,
                            content=(llm_result.text or "").strip(),
                            reasoning=(getattr(llm_result, "reasoning", None) or "").strip()
                            or None,
                        )
                    )
                    working.append(
                        ChatMessage(role=MessageRole.USER, content=FORCE_TOOL_USER_PROMPT)
                    )
                    if round_idx >= limit - 1:
                        return _blocked_no_tool(
                            code="LLM_ROUND_NO_SUCCESSFUL_TOOL",
                            working=working,
                            all_results=all_results,
                            iterations=iterations,
                            used_tools=used_tools,
                            detail="model finalized without calling tools",
                        )
                    continue

                if not final:
                    logger.info(
                        "execute_llm_round: blocked non-final LLM text iteration=%s",
                        iterations,
                    )
                    working.append(
                        ChatMessage(
                            role=MessageRole.ASSISTANT,
                            content=(llm_result.text or "").strip(),
                            reasoning=(getattr(llm_result, "reasoning", None) or "").strip()
                            or None,
                        )
                    )
                    working.append(
                        ChatMessage(
                            role=MessageRole.USER,
                            content=FINAL_ANSWER_RETRY_PROMPT,
                        )
                    )
                    if round_idx >= limit - 1:
                        err = _error_result(
                            "LLM_ROUND_REASONING_BLOCKED",
                            params={
                                "reason": "model returned internal reasoning instead of final answer",
                                "user_message": NO_DATA_USER_MESSAGE,
                            },
                            data={
                                "iterations": iterations,
                                "used_tools": used_tools,
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
                    continue

                if not _answer_grounded_in_tools(final, all_results):
                    return _blocked_no_tool(
                        code="LLM_ROUND_UNGROUNDED",
                        working=working,
                        all_results=all_results,
                        iterations=iterations,
                        used_tools=used_tools,
                        detail="answer not grounded in ToolResult",
                    )

                return LLMRoundResult(
                    ok=True,
                    text=final,
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
                    params={
                        "error": str(exc)[:400],
                        "user_message": NO_DATA_USER_MESSAGE,
                    },
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
                "execute_llm_round iteration=%s tools=%s ok=%s",
                iterations,
                [(r.tool, r.ok) for r in round_results],
                has_successful_tool_result(all_results),
            )

        # Исчерпан лимит.
        if not has_successful_tool_result(all_results):
            return _blocked_no_tool(
                code="LLM_ROUND_NO_SUCCESSFUL_TOOL",
                working=working,
                all_results=all_results,
                iterations=iterations,
                used_tools=used_tools,
                detail="max iterations without successful tool",
            )
        err = _error_result(
            "LLM_ROUND_MAX_ITERATIONS",
            params={
                "max_iterations": limit,
                "user_message": NO_DATA_USER_MESSAGE,
            },
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
            params={"error": str(exc)[:400], "user_message": NO_DATA_USER_MESSAGE},
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
