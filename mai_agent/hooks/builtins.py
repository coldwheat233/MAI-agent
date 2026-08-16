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

# 暂无内置 hook 注册。
