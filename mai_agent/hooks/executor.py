"""Hook 执行器 — 匹配 + 执行 Hook 链。

对应 Claude Code 的 utils/hooks.ts 中的 executeHooks()。
"""

from __future__ import annotations

import logging
from typing import Any

from mai_agent.hooks.types import (
    HookEvent,
    HookRegistry,
    PreToolUseResult,
    hook_registry,
)

logger = logging.getLogger(__name__)


async def execute_hooks(
    event: HookEvent,
    tool_name: str = "",
    tool_input: dict[str, Any] | None = None,
    registry: HookRegistry | None = None,
) -> list[PreToolUseResult]:
    """执行所有匹配的 Hook，收集结果。

    对应 Claude Code behavior:
      - 并行启动所有匹配的 hook 子进程
      - 收集返回的 JSON 结果
      - PreToolUse: 收集所有 PermissionResult

    Args:
        event: 触发事件类型
        tool_name: 工具名（PreToolUse/PostToolUse 事件需要）
        tool_input: 工具输入参数
        registry: Hook 注册表，默认全局单例

    Returns:
        所有 Hook 的执行结果列表
    """
    reg = registry or hook_registry
    matched = reg.match(event, tool_name)

    if not matched:
        return []

    results: list[PreToolUseResult] = []
    for matcher, callback in matched:
        try:
            result = await callback(tool_name, tool_input or {})
            if result is not None:
                results.append(result)
        except Exception as exc:
            logger.warning(
                "Hook '%s' 执行异常 (event=%s, tool=%s): %s",
                matcher.hook_name, event, tool_name, exc,
            )

    return results
