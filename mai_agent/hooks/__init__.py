"""Hook 系统入口"""

from mai_agent.hooks.types import (
    HookEvent,
    HookCallback,
    HookMatcher,
    PreToolUseResult,
    HookRegistry,
    hook_registry,
)
from mai_agent.hooks.executor import execute_hooks
from mai_agent.hooks.gate import can_use_tool
from mai_agent.hooks import builtins  # noqa: F401 — 注册内置 hook

__all__ = [
    "HookEvent",
    "HookCallback",
    "HookMatcher",
    "PreToolUseResult",
    "HookRegistry",
    "hook_registry",
    "execute_hooks",
    "can_use_tool",
]
