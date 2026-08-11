"""沙箱策略 — 对 Bash 命令的受限执行控制。

对应 Claude Code 的沙箱/权限执行模型。在 BashTool 执行命令前，策略模块
对命令做静态审查，决定 allow / deny / ask，并可约束工作目录与可写路径。

策略层次（最严匹配优先）:
  1. 黑名单命令 → deny（如 rm -rf /, :(){ :|:& };:, shutdown）
  2. 路径越界写 → deny（写到 cwd 之外，除非在 writable_paths 白名单）
  3. 白名单模式 → 仅允许白名单内的命令前缀
  4. 网络命令 → 可选 deny（curl/wget/scp/ssh）

沙箱不是容器级隔离（那是 Docker/Firejail 的职责），而是命令层审查 + 路径约束。
设计目标：在个人开发工作流中拦截高危误操作，而非防御恶意 LLM。
"""

from mai_agent.sandbox.policy import (
    SandboxPolicy,
    SandboxDecision,
    SandboxViolation,
    default_policy,
    strict_policy,
    validate_command,
)

__all__ = [
    "SandboxPolicy",
    "SandboxDecision",
    "SandboxViolation",
    "default_policy",
    "strict_policy",
    "validate_command",
]
