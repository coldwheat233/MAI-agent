"""工具编排 — 对应 Claude Code 的 services/tools/toolOrchestration.ts。

参考 DeepSeek Harness 的副作用分级设计（maxParallelToolCalls 验收方法）:
  - 只读工具（is_concurrency_safe=True）→ 并发执行
  - 独立写入工具（write_targets 可判定且互不重叠）→ 并发执行
  - 共享写入 / 外部副作用（写目标重叠或无法静态判定）→ 串行执行

与"一刀切写串行"的区别: LLM 并行发起 N 个写不同文件的 Write，
旧实现全串行（延迟 = 读 + 写1 + 写2 + ...），新实现中独立写并发（延迟 ≈ 读 + max(写)）。
只有真正写同一目标（数据血缘冲突）的工具才串行——保留因果安全，不牺牲吞吐。
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


def _resolve_targets(block: ToolUseBlock, registry: ToolRegistry) -> list[str]:
    """解析工具调用的写目标（write_targets 声明）。未知工具/无法判定返回 []。"""
    try:
        tool = registry.get(block.name)
        return tool.write_targets(block.input) or []
    except Exception:
        return []


def partition_by_safety(
    blocks: list[ToolUseBlock],
    registry: ToolRegistry,
) -> tuple[list[ToolUseBlock], list[ToolUseBlock], list[ToolUseBlock]]:
    """将工具调用分区为三组。

    对齐 DSH 副作用分级:
      - 只读（is_concurrency_safe=True）→ concurrent_reads
      - 独立写入（write_targets 非空且与其他写不重叠）→ concurrent_writes
      - 共享写入 / 外部副作用（目标重叠、无法判定、未知工具）→ serial

    Returns:
        (concurrent_reads, concurrent_writes, serial)
    """
    reads: list[ToolUseBlock] = []
    writes: list[ToolUseBlock] = []

    for block in blocks:
        try:
            tool = registry.get(block.name)
            if tool.is_concurrency_safe:
                reads.append(block)
            else:
                writes.append(block)
        except KeyError:
            # 未知工具默认按串行处理（安全优先）
            writes.append(block)

    if not writes:
        return reads, [], []

    # 对写工具做重叠检测：同一目标的写必须串行
    # target → 第一个声明该目标的 block 下标（0-based in writes）
    target_owners: dict[str, int] = {}
    owner_serial: set[int] = set()      # 因重叠被降级为串行的写
    for i, block in enumerate(writes):
        targets = _resolve_targets(block, registry)
        if not targets:
            # 无法静态判定目标（如 Bash）→ 保守串行
            owner_serial.add(i)
            continue
        for t in targets:
            if t in target_owners and target_owners[t] != i:
                # 与其他写工具写同一目标 → 两者都串行
                owner_serial.add(i)
                owner_serial.add(target_owners[t])
            else:
                target_owners.setdefault(t, i)

    concurrent_writes = [b for i, b in enumerate(writes) if i not in owner_serial]
    serial = [b for i, b in enumerate(writes) if i in owner_serial]

    return reads, concurrent_writes, serial


async def _run_one(
    block: ToolUseBlock,
    registry: ToolRegistry,
    context: RunContext,
    semaphore: asyncio.Semaphore | None = None,
) -> ToolExecutionResult:
    """执行单个工具调用（带并发上限）。"""
    async def _exec() -> ToolExecutionResult:
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

    if semaphore is not None:
        async with semaphore:
            return await _exec()
    return await _exec()


async def run_tools(
    blocks: list[ToolUseBlock],
    registry: ToolRegistry,
    context: RunContext,
) -> AsyncIterator[ToolExecutionResult]:
    """执行工具调用 — 只读并发 → 独立写并发 → 共享写/副作用串行。

    对齐 DSH 副作用分级执行管线:
      1. 只读组: 并行执行（上限 MAX_CONCURRENT_TOOLS）
      2. 独立写入组: 并行执行（写目标互不重叠，安全）
      3. 串行组: 共享写入 / 外部副作用 / 无法判定目标，逐个执行

    写失败不回滚（Agent 场景下由 LLM 看到错误后重新决策），
    与"串行写 + Saga 补偿"相比，独立写并发不会产生"部分成功需补偿"的新语义。
    """
    reads, concurrent_writes, serial = partition_by_safety(blocks, registry)

    # 1+2. 只读 + 独立写入并发执行
    concurrent_all = reads + concurrent_writes
    if concurrent_all:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)
        tasks = [_run_one(b, registry, context, semaphore) for b in concurrent_all]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error("并发工具执行异常: %s", r)
            else:
                yield r

    # 3. 串行执行共享写入 / 外部副作用
    for block in serial:
        result = await _run_one(block, registry, context)
        yield result
