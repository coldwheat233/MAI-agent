"""子Agent孵化工具 — 对应 Claude Code 的 AgentTool。

AgentTool 让主 Agent 可以孵化子 Agent 来执行特定任务。
子 Agent 拥有独立的 messages[] 和允许工具白名单。

注意：此模块不依赖 core/loop.py，避免循环导入。
子Agent 自己运行轻量循环，复用 llm.Client 和 tools.orchestration。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext, ToolResult
from mai_agent.tools.registry import registry
from mai_agent.tools.orchestration import (
    ToolUseBlock,
    run_tools,
    ToolExecutionResult,
)
from mai_agent.llm.client import LLMClient
from mai_agent.brains.definitions import ALL_BRAINS

logger = logging.getLogger(__name__)


class AgentToolInput(ToolInput):
    brain: str = Field(description="要激活的脑名称: dev_explorer | dev_validator | knowledge_explorer")
    prompt: str = Field(description="发给子Agent的任务描述")
    max_turns: int = Field(default=10, description="子Agent最大轮数")
    model: Optional[str] = Field(default=None, description="可选: 指定模型")


class AgentTool(Tool):
    """孵化子 Agent 以执行特定脑的任务。

    Claude Code 对应物: AgentTool + runAgent.ts.

    子Agent:
      - 有独立的 messages[]（从 brain 的 system_prompt 开始）
      - 只允许 brain 定义的 allowed_tools
      - 有独立的 max_turns 限制
      - 完成后返回 AgentOutput
    """
    name = "Agent"
    description = "孵化一个子 Agent 来执行特定脑的任务（如 dev_explorer, dev_validator）"
    input_schema = AgentToolInput
    is_concurrency_safe = False

    async def call(self, input: AgentToolInput, context: RunContext) -> str:
        brain_name = input.brain.strip()

        definition = ALL_BRAINS.get(brain_name)
        if definition is None:
            available = ", ".join(ALL_BRAINS.keys())
            return f"[ERROR] 未知的脑: {brain_name}。可用: {available}"

        # 构建子Agent的消息历史
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": definition.prompt},
            {"role": "user", "content": input.prompt},
        ]

        # 过滤工具：只保留 allowed_tools 中的工具
        from mai_agent.config import get_config
        config = get_config()
        sub_llm = LLMClient(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url or "https://api.deepseek.com/v1",
            model=input.model or config.llm_model,
        )
        tools = [
            t for t in registry.to_openai_schemas("auto")
            if t["function"]["name"] in definition.allowed_tools
        ]

        # 子Agent 独立的轻量循环 — 不依赖 core/loop.py
        for step in range(1, input.max_turns + 1):
            response = await sub_llm.chat(messages, tools=tools)
            messages.append(_make_assistant_msg(response))

            if not response.tool_calls:
                # 收敛 → 返回纯文本
                return f"[子Agent: {brain_name}]\n{response.content or '(empty)'}"

            # 执行工具
            blocks = [
                ToolUseBlock(
                    id=tc.id,
                    name=tc.function.name if tc.function else "",
                    input=_safe_parse_json(tc.function.arguments if tc.function else "{}"),
                )
                for tc in response.tool_calls
            ]

            exec_results: list[ToolExecutionResult] = []
            async for result in run_tools(blocks, registry, context):
                exec_results.append(result)

            for block, er in zip(blocks, exec_results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": block.id,
                    "content": er.message.content,
                })

        return f"[子Agent: {brain_name}] 达到最大步数 {input.max_turns}"


# ── 辅助 ─────────────────────────────────────────────────


def _safe_parse_json(s: str) -> dict[str, Any]:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}


def _make_assistant_msg(response: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant"}
    if response.content is not None:
        msg["content"] = response.content
    if response.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name if tc.function else "",
                    "arguments": tc.function.arguments if tc.function else "{}",
                },
            }
            for tc in response.tool_calls
        ]
    return msg


registry.register(AgentTool())
