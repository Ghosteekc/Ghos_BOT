"""Точки подключения LLM — документация для будущей интеграции.

Модель здесь НЕ вызывается. Только маркеры мест в пайплайне.
"""

from __future__ import annotations

# --- Куда добавить вызов модели ---

HOOK_PROMPT_BUILDER = (
    "bot.services.ghosteek_ai.llm.prompt_builder.PromptBuilder.build"
)
# System + history + AIContext + tool results + user → list[ChatMessage]

HOOK_LLM_PROVIDER = (
    "bot.services.ghosteek_ai.llm.provider.LLMProvider.generate"
)
# messages → LLMGenerateResult (OllamaProvider / QwenLLMProvider)

HOOK_RESPONSE_PARSER = (
    "bot.services.ghosteek_ai.llm.response_parser.ResponseParser.parse"
)
# raw provider payload → text / tool_calls

HOOK_RESPONSE_GENERATOR = (
    "bot.services.ghosteek_ai.generator.llm_generator.QwenResponseGenerator.generate"
)
# PromptBuilder → provider → parser → str

HOOK_OLLAMA_GENERATOR = (
    "bot.services.ghosteek_ai.generator.llm_generator.OllamaResponseGenerator.generate"
)

HOOK_SERVICE_SWAP_GENERATOR = (
    "bot.services.ghosteek_ai.service.ask_ghosteek_ai"
)
# get_response_generator("ollama"|"qwen") вместо template (feature-flag)

HOOK_PLANNER_TOOL_CALLS = (
    "bot.services.ghosteek_ai.planner.planner.Planner.build"
)
# вместо INTENT_TOOL_MAP: model tool_calls → ToolCaller.execute_qwen_tool_calls

HOOK_TOOL_LOOP = (
    "bot.services.ghosteek_ai.tools.llm_round.execute_llm_round"
)
# wired: run_llm_agent → execute_llm_round (≤5) → ToolCaller.execute_qwen_tool_calls
# Planner.execute_plan — только fallback при ошибке/недоступности LLM

HOOK_MEMORY_SUMMARY = (
    "bot.services.ghosteek_ai.memory.summary"
)
# rule-based compress → LLM summarize conversation

HOOK_SAFETY_FACTCHECK = (
    "bot.services.ghosteek_ai.safety.layer.SafetyLayer.apply"
)
# сверка чисел ответа с AIContext (score/synergy) после LLM текста

HOOK_FORMAT_TOOLS_FOR_LLM = (
    "bot.services.ghosteek_ai.tools.qwen.format_tool_results_for_llm"
)
# уже готово: JSON content + call_id → messages role=tool

HOOK_EXPORT_TOOLS = (
    "bot.services.ghosteek_ai.tools.qwen.export_qwen_tools"
)
# уже готово: registry.qwen_tools() → tools[] для API

QWEN_HOOKS: tuple[str, ...] = (
    HOOK_PROMPT_BUILDER,
    HOOK_LLM_PROVIDER,
    HOOK_RESPONSE_PARSER,
    HOOK_RESPONSE_GENERATOR,
    HOOK_OLLAMA_GENERATOR,
    HOOK_SERVICE_SWAP_GENERATOR,
    HOOK_PLANNER_TOOL_CALLS,
    HOOK_TOOL_LOOP,
    HOOK_MEMORY_SUMMARY,
    HOOK_SAFETY_FACTCHECK,
    HOOK_FORMAT_TOOLS_FOR_LLM,
    HOOK_EXPORT_TOOLS,
)
