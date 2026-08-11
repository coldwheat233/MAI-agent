"""Hook 类型定义 — 对应 Claude Code 的 types/hooks.ts。

Hook 系统分三类事件:
  - PreToolUse:  工具执行前（可阻止）
  - PostToolUse: 工具执行后（通知/日志）
  - Session 事件: 会话开始/结束/Stop
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional


class HookEvent(str, Enum):
    """Hook 事件类型 — 对应 Claude Code 的 HookEvent。"""
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    STOP = "Stop"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    NOTIFICATION = "Notification"


@dataclass
class PreToolUseResult:
    """PreToolUse hook 的返回结果。

    对应 Claude Code 的 PermissionResult:
      - allow: 放行
      - deny:  阻止并给出理由
      - ask:   需要用户确认
    """
    decision: str  # "allow" | "deny" | "ask"
    reason: str = ""
    modified_input: Optional[dict[str, Any]] = None
    """如果提供，将替换原始工具输入参数"""


@dataclass
class HookMatcher:
    """Hook 匹配器 — 决定哪个 hook 对哪个事件响应。

    对应 Claude Code 的 HookMatcher:
      支持工具名正则匹配、事件类型过滤、来源过滤。
    """
    event: HookEvent
    hook_name: str
    tool_pattern: str = ".*"  # 正则匹配工具名
    source: str = "user"  # user | plugin | skill
    priority: int = 50  # 越小越先执行

    def matches(self, event: HookEvent, tool_name: str = "") -> bool:
        if self.event != event:
            return False
        if tool_name and not re.match(self.tool_pattern, tool_name):
            return False
        return True


# HookCallback: 异步函数，接收 (工具名, 输入参数字典, 上下文) → PreToolUseResult | None
HookCallback = Callable[..., Awaitable[Optional[PreToolUseResult]]]


class HookRegistry:
    """全局 Hook 注册表。

    Claude Code 对应物: hooks/ 目录下的注册逻辑 + sessionHooks。
    """

    def __init__(self):
        self._matchers: list[HookMatcher] = []
        self._callbacks: dict[str, HookCallback] = {}

    def register(
        self,
        name: str,
        callback: HookCallback,
        event: HookEvent = HookEvent.PRE_TOOL_USE,
        tool_pattern: str = ".*",
        source: str = "user",
        priority: int = 50,
    ) -> None:
        """注册一个 Hook。

        Args:
            name: 唯一名称
            callback: 异步回调函数
            event: 触发事件类型
            tool_pattern: 匹配工具名的正则（如 "Bash|Edit|Write"）
            source: 来源 (user/plugin/skill)
            priority: 优先级（越小越先执行）
        """
        matcher = HookMatcher(
            event=event,
            hook_name=name,
            tool_pattern=tool_pattern,
            source=source,
            priority=priority,
        )
        self._matchers.append(matcher)
        self._callbacks[name] = callback

    def match(
        self,
        event: HookEvent,
        tool_name: str = "",
    ) -> list[tuple[HookMatcher, HookCallback]]:
        """查找匹配 event + tool_name 的所有 Hook，按 priority 排序。"""
        matched: list[tuple[HookMatcher, HookCallback]] = []
        for m in self._matchers:
            if m.matches(event, tool_name):
                cb = self._callbacks.get(m.hook_name)
                if cb:
                    matched.append((m, cb))
        matched.sort(key=lambda x: x[0].priority)
        return matched

    def clear(self) -> None:
        self._matchers.clear()
        self._callbacks.clear()


# ── 全局单例 ─────────────────────────────────────────────

hook_registry = HookRegistry()
"""全局 Hook 注册表。"""
