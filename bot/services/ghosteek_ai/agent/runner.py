"""LLM Agent Mode — reasoning loop: LLM выбирает tools, не Planner.

PromptBuilder → LLM → tool_calls → ToolCaller → role=tool → LLM → …
Максимум 5 итераций (execute_llm_round).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder
from bot.services.ghosteek_ai.llm.provider import LLMProvider
from bot.services.ghosteek_ai.llm.reasoning_filter import (
    DEFAULT_REASONING_FILTER,
    finalize_user_facing_text,
)
from bot.services.ghosteek_ai.models import Plan
from bot.services.ghosteek_ai.tools.base import ToolCaller, ToolRegistry
from bot.services.ghosteek_ai.tools.llm_round import (
    MAX_LLM_ROUND_ITERATIONS,
    execute_llm_round,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = MAX_LLM_ROUND_ITERATIONS  # 5


@dataclass
class AgentRunResult:
    text: str
    tool_names: list[str] = field(default_factory=list)
    rounds: int = 0
    used_tool_calling: bool = False


async def run_llm_agent(
    ctx: AIContext,
    *,
    provider: LLMProvider,
    caller: ToolCaller,
    registry: ToolRegistry,
    planner_plan: Plan | None = None,
    prompt_builder: PromptBuilder | None = None,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
) -> AgentRunResult:
    """
    Reasoning loop:

      PromptBuilder → LLM → tool_calls → execute_qwen_tool_calls
        → ToolResult as role=tool → LLM → … ≤5 → финальный текст

    ``planner_plan`` больше не влияет на выбор tools (оставлен в сигнатуре
    для совместимости; подсказка в prompt не передаётся).
    """
    del planner_plan  # LLM выбирает tools сам

    if not provider.supports_tools():
        raise RuntimeError("LLM provider does not support tool calling")

    builder = prompt_builder or PromptBuilder()
    tools_schema = registry.openai_tools()
    if not tools_schema:
        raise RuntimeError("Tool registry has no tools for agent mode")

    messages = builder.build(
        ctx,
        include_tool_results=False,
        planner_recommendation=None,
    )

    round_result = await execute_llm_round(
        messages,
        ctx,
        provider=provider,
        caller=caller,
        tools=tools_schema,
        max_iterations=max_tool_rounds,
    )

    if not round_result.ok:
        err = round_result.error
        code = err.error_code if err is not None else "LLM_ROUND_ERROR"
        detail = ""
        if err is not None and isinstance(err.error_params, dict):
            detail = str(err.error_params.get("error") or "")
        msg = f"agent_round_failed: {code}"
        if detail:
            msg = f"{msg}: {detail}"
        raise RuntimeError(msg)

    text = finalize_user_facing_text(
        content=round_result.text,
        filter=DEFAULT_REASONING_FILTER,
    )
    if not text:
        raise RuntimeError(
            "Agent mode: LLM returned internal reasoning instead of a final answer"
        )

    tool_names = [r.tool for r in round_result.tool_results]
    logger.info(
        "ghosteek_ai agent_loop ok iterations=%s used_tools=%s tools=%s",
        round_result.iterations,
        round_result.used_tools,
        tool_names,
    )
    return AgentRunResult(
        text=text,
        tool_names=tool_names,
        rounds=round_result.iterations,
        used_tool_calling=round_result.used_tools,
    )
