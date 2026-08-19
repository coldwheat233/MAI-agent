"""内置 Hook — 系统级 PreToolUse / PostToolUse hooks。

历史：这里的 sandbox-file-write hook 用模块级全局状态（set_sandbox_hook_state /
_current_sandbox / _current_cwd）检查 Write/Edit 的文件路径越界。多工作区并发时该
全局状态会串台（Bash 走的是 per-engine 的 context.session_state，唯独 Write/Edit
走全局）。

现在：写路径沙箱检查已迁移到 Write/Edit 工具内部，用
RunContext.session_state["sandbox"] + context.cwd（见 sandbox/policy.py 的
check_file_write），与 Bash 一致、按工作区隔离。

此模块保留为内置 hook 的注册扩展点（rate-limit / audit-log / auto-backup 等）。
"""

from __future__ import annotations

import logging

from mai_agent.hooks.types import HookEvent, hook_registry

logger = logging.getLogger(__name__)


async def _post_tool_audit(ctx: dict) -> None:
    """PostToolUse 审计 hook — 工具执行后记录审计日志。

    双写:
      1. logging 层（终端可见）
      2. structured_logger → .mai/logs/{session_id}.jsonl（与现有日志体系一致）

    ctx: {event, tool_name, tool_input, tool_result, is_error, duration_ms,
          tool_call_id, session_id, project_root}
    返回 None（PostToolUse 不产生权限结果）。
    """
    tool_name = ctx.get("tool_name", "?")
    is_error = ctx.get("is_error", False)
    duration = ctx.get("duration_ms", 0)
    result_preview = str(ctx.get("tool_result", ""))[:120].replace("\n", " ")
    level = logging.WARNING if is_error else logging.INFO
    logger.log(
        level,
        "[hook:audit] tool=%s ok=%s dur=%.0fms result=%s",
        tool_name, not is_error, duration, result_preview,
    )

    # 写入 structured_logger jsonl（session 级，与 turn_converge 等事件同文件）
    try:
        from mai_agent.services.structured_logger import get_logger
        slog = get_logger(ctx.get("session_id", "?"), ctx.get("project_root", "."))
        slog.log(
            "tool_audit",
            {
                "tool": tool_name,
                "is_error": is_error,
                "duration_ms": round(duration, 2),
                "result": result_preview,
                "tool_call_id": ctx.get("tool_call_id", ""),
            },
            level="WARN" if is_error else "INFO",
        )
    except Exception as exc:
        logger.debug("audit -> structured_logger 失败: %s", exc)


# 注册内置 PostToolUse 审计 hook（匹配所有工具）
hook_registry.register(
    "builtin-audit-log",
    _post_tool_audit,
    event=HookEvent.POST_TOOL_USE,
    tool_pattern=".*",
    source="builtin",
    priority=100,
)
