"""工具编排 — 对应 Claude Code 的 services/tools/toolOrchestration.ts。

将 tool_use blocks 分区为并发安全/非并发安全两组，分别执行。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from mai_agent.tools.base import Tool, ToolResult, RunContext
from mai_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# 最大并发数
MAX_CONCURRENT_TOOLS = 10


@dataclass
class ToolUseBlock:
    """LLM 返回的单个工具调用。

    对应 Claude Code 的 ToolUseBlock (from @anthropic-ai/sdk).
    """
    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolExecutionResult:
    message: ToolResult
    context_modifier: Any | None = None


def partition_by_safety(
    blocks: list[ToolUseBlock],
    registry: ToolRegistry,
) -> tuple[list[ToolUseBlock], list[ToolUseBlock]]:
    """将工具调用分区为并发安全和串行两组。

    Claude Code 中的规则:
      - FileReadTool, GrepTool, GlobTool → concurrent (只读)
      - FileEditTool, FileWriteTool, BashTool → serial (有写操作)

    Returns:
        (concurrent_blocks, serial_blocks)
    """
    concurrent: list[ToolUseBlock] = []
    serial: list[ToolUseBlock] = []

    for block in blocks:
        try:
            tool = registry.get(block.name)
            if tool.is_concurrency_safe:
                concurrent.append(block)
            else:
                serial.append(block)
        except KeyError:
            # 未知工具默认按串行处理（安全优先）
            serial.append(block)

    return concurrent, serial


async def run_tools(
    blocks: list[ToolUseBlock],
    registry: ToolRegistry,
    context: RunContext,
) -> AsyncIterator[ToolExecutionResult]:
    """执行工具调用 — 先并发组，再串行组。

    Claude Code 对应物: toolOrchestration.ts 中的 runTools().

    执行顺序:
      1. 并发组: 所有只读工具并行执行（上限 MAX_CONCURRENT_TOOLS）
      2. 串行组: 写操作逐个执行
    """
    # 1. 分区
    concurrent_blocks, serial_blocks = partition_by_safety(blocks, registry)

    # 2. 并发执行只读工具
    if concurrent_blocks:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)

        async def run_one(block: ToolUseBlock) -> ToolExecutionResult:
            async with semaphore:
                try:
                    tool = registry.get(block.name)
                    block.input["_tool_use_id"] = block.id
                    result = await tool.execute(block.input, context)
                    return ToolExecutionResult(message=result)
                except KeyError:
                    return ToolExecutionResult(
                        message=ToolResult(
                            tool_use_id=block.id,
                            content=f"[ERROR] 未知工具: {block.name}",
                            is_error=True,
                        )
                    )

        tasks = [run_one(b) for b in concurrent_blocks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error("并发工具执行异常: %s", r)
            else:
                yield r

    # 3. 串行执行写操作
    for block in serial_blocks:
        try:
            tool = registry.get(block.name)
            block.input["_tool_use_id"] = block.id
            result = await tool.execute(block.input, context)
            yield ToolExecutionResult(message=result)
        except KeyError:
            yield ToolExecutionResult(
                message=ToolResult(
                    tool_use_id=block.id,
                    content=f"[ERROR] 未知工具: {block.name}",
                    is_error=True,
                )
            )
