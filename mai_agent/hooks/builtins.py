"""内置 Hook — 系统级 PreToolUse / PostToolUse hooks。

与 Claude Code 的 built-in hooks 对应：
  - sandbox-file-write: Write/Edit 工具的文件路径沙箱检查
  - 后续可加: rate-limit, audit-log, auto-backup-before-edit
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from mai_agent.hooks.types import (
    HookEvent,
    PreToolUseResult,
    hook_registry,
)

logger = logging.getLogger(__name__)

# ── 模块级沙箱策略引用（由 engine.start() 设置）────────────

_current_sandbox: Any = None  # SandboxPolicy | None
_current_cwd: str = "."


def set_sandbox_hook_state(policy: Any, cwd: str = ".") -> None:
    """engine 启动时调用，设置当前会话的沙箱策略。"""
    global _current_sandbox, _current_cwd
    _current_sandbox = policy
    _current_cwd = cwd


def _get_writable_roots() -> list[Path]:
    """获取当前允许写入的根路径列表。"""
    roots = [Path(_current_cwd).resolve()]
    if _current_sandbox and hasattr(_current_sandbox, "writable_paths"):
        for p in _current_sandbox.writable_paths:
            roots.append(Path(p).resolve())
    return roots


# ── Sandbox File-Write Hook ──────────────────────────────


async def _sandbox_file_write_hook(
    tool_name: str,
    tool_input: dict[str, Any],
) -> Optional[PreToolUseResult]:
    """PreToolUse hook: 检查 Write/Edit 的文件路径是否越界。

    使用当前会话的 SandboxPolicy 判断文件写入目标是否在允许范围内。
    仅在 sandbox 激活时（policy.active == True）生效。
    """
    if _current_sandbox is None or not getattr(_current_sandbox, "active", False):
        return None  # 沙箱未激活，不干预

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None  # 无文件路径参数

    tgt = Path(file_path)
    if not tgt.is_absolute():
        tgt = (Path(_current_cwd) / tgt)
    tgt = tgt.resolve()

    # /dev/null 等设备放行
    if str(tgt) in ("/dev/null", "NUL"):
        return None

    roots = _get_writable_roots()

    # 检查目标是否在任一允许根路径之下
    for root in roots:
        try:
            tgt.relative_to(root)
            break  # 在允许范围内
        except ValueError:
            continue
    else:
        # 不在任何允许根路径之下 → 拒绝
        allowed = ", ".join(str(r) for r in roots)
        return PreToolUseResult(
            decision="deny",
            reason=(
                f"沙箱拦截: {tool_name} 写入目标 '{file_path}' 不在允许路径内。"
                f"允许范围: {allowed}"
            ),
        )

    return None  # 通过


# ── 注册 ─────────────────────────────────────────────────

hook_registry.register(
    name="sandbox-file-write",
    callback=_sandbox_file_write_hook,
    event=HookEvent.PRE_TOOL_USE,
    tool_pattern="^(Write|Edit|FileWrite|FileEdit)$",
    source="system",
    priority=10,  # 高优先级（早执行）
)
logger.debug("沙箱 PreToolUse hook 已注册: sandbox-file-write → Write|Edit")
