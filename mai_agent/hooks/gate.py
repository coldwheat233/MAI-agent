"""权限门控 — 对应 Claude Code 的 hooks/useCanUseTool.ts。

在工具执行前，运行 PreToolUse Hook 链来决定是否放行。
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
from mai_agent.hooks.executor import execute_hooks
from mai_agent.core.models import PermissionResult

logger = logging.getLogger(__name__)


async def can_use_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    permission_mode: str = "auto",
    registry: HookRegistry | None = None,
) -> PermissionResult:
    """PreToolUse 门控 — 判断工具是否允许执行。

    对应 Claude Code 的 useCanUseTool hook。

    三层判断（按优先级）:
      1. Hook 层 — 所有模式都运行 PreToolUse hooks
         - deny  → 直接阻止（所有模式生效）
         - ask   → auto/plan 下自动拒绝，manual 下弹给用户
      2. 模式层 — plan 模式额外限制只读工具
      3. 默认 — auto/manual 下所有通过则放行

    Returns:
        PermissionResult(allow=True/False, reason=..., modified_input=...)
    """
    reg = registry or hook_registry

    # 第一层: 所有模式都运行 PreToolUse hooks
    results = await execute_hooks(HookEvent.PRE_TOOL_USE, tool_name, tool_input, reg)
    for r in results:
        if r.decision == "deny":
            return PermissionResult(allow=False, reason=r.reason)
        if r.decision == "ask":
            if permission_mode == "manual":
                # 需要用户确认
                return PermissionResult(
                    allow=False,
                    reason=f"需要确认: {r.reason}",
                )
            else:
                # auto/plan 模式下 ask 即 deny
                return PermissionResult(
                    allow=False,
                    reason=f"自动拒绝（{permission_mode} 模式）: {r.reason}",
                )

    # 第二层: plan 模式的只读限制
    if permission_mode == "plan":
        read_only_tools = {"Read", "Grep", "Glob", "WebSearch", "WebFetch",
                          "GitStatus", "GitDiff", "GitLog", "MemoryRead",
                          "MemorySearch", "MemoryList", "ListWorktrees",
                          "TaskList", "TaskGet", "TaskOutput"}
        if tool_name not in read_only_tools:
            return PermissionResult(
                allow=False,
                reason=f"Plan 模式下不允许使用写工具 '{tool_name}'。"
                f"只允许: {', '.join(sorted(read_only_tools))}。",
            )
        return PermissionResult(allow=True)

    # 第三层: auto / manual 通过则放行
    return PermissionResult(allow=True)
