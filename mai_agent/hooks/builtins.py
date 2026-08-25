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
import re

from mai_agent.hooks.types import HookEvent, PreToolUseResult, hook_registry

logger = logging.getLogger(__name__)


async def _guard_dangerous_bash(ctx: dict) -> PreToolUseResult | None:
    """PreToolUse 守卫 — 拦截 Bash 中的破坏性/危险命令。

    匹配规则（大小写不敏感，命令级前缀匹配）:
      - rm -rf / 或 rm -rf C:\\ （删除根目录/系统盘）
      - format / mkfs（格式化磁盘）
      - del /s /q（Windows 递归静默删除）
      - shutdown /s /f（强制关机）
      - rd /s /q（Windows 递归删除目录）
    返回 deny 阻止执行，否则 None（放行）。
    """
    if ctx.get("tool_name") != "Bash":
        return None
    tool_input = ctx.get("tool_input") or {}
    command = str(tool_input.get("command", ""))
    if not command:
        return None
    cmd = command.strip().lower()

    # (正则, 说明)
    patterns: list[tuple[re.Pattern, str]] = [
        (re.compile(r"^\s*(rm\s+(-[a-z]*\s+)*[-/]?\s*$|rm\s+.*\s+/\s*$|rm\s+-rf\s+/\s*$)"), "删除根目录"),
        (re.compile(r"^\s*rm\s+(-[a-z]*\s+)*(\/|c:\\|d:\\|e:\\)\s*$"), "删除根目录/系统盘"),
        (re.compile(r"^\s*rm\s+-[a-z]*r[a-z]*f[a-z]*\s+(\/|\\|[a-z]:\\?)\s*$"), "递归强制删除根目录"),
        # 系统关键目录（绝对路径的 /home /etc /usr /var /boot /Windows /Program Files /System32）
        (re.compile(r"^\s*rm\s+(-[a-z]*\s+)*(/home|/etc|/usr|/var|/boot|/root|/bin|/sbin)(\s|$)"), "删除系统关键目录"),
        (re.compile(r"^\s*rm\s+(-[a-z]*\s+)*(c:\\windows|d:\\windows|.*\\system32)(\s|$)"), "删除 Windows 系统目录"),
        (re.compile(r"^\s*(format|mkfs)[\s.]"), "格式化磁盘"),
        (re.compile(r"^\s*del\s+/[sq]"), "Windows 递归删除"),
        (re.compile(r"^\s*rd\s+/[sq]"), "Windows 递归删除目录"),
        (re.compile(r"^\s*shutdown\s+.*/s\b.*/f\b"), "强制关机"),
        (re.compile(r"^\s*(init\s+0|reboot\s*$|poweroff\s*$|halt\s*$)"), "关机/重启系统"),
    ]

    for pattern, label in patterns:
        if pattern.match(cmd):
            logger.warning("[guardrail] 拦截危险命令 (%s): %s", label, command[:100])
            return PreToolUseResult(
                decision="deny",
                reason=f"危险命令被 Guardrail 拦截: {label}。如需执行请手动在终端操作。",
            )
    return None


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

# 注册内置 PreToolUse 守卫（只拦 Bash 危险命令，优先级最高先执行）
hook_registry.register(
    "builtin-guard-dangerous-bash",
    _guard_dangerous_bash,
    event=HookEvent.PRE_TOOL_USE,
    tool_pattern="Bash",
    source="builtin",
    priority=10,
)
