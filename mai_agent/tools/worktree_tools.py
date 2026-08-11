"""工作区隔离工具 — 对应 Claude Code 的 EnterWorktree / ExitWorktree。

使用 git worktree 创建隔离的工作目录 + 独立分支，让 Agent 在副本上修改代码，
不影响主工作区。修改完成后可保留或移除 worktree。

对应 Claude Code 的 worktree 模式:
  - EnterWorktree: git worktree add → 切换 session cwd 到新 worktree
  - ExitWorktree:  返回原 cwd，可选保留或移除 worktree

设计:
  - worktree 存放在 .mai/worktrees/<name>/
  - base ref: fresh(从 origin/default 分支) 或 head(从当前 HEAD)
  - 状态记录在 RunContext.session_state["worktree_stack"]
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry

logger = logging.getLogger(__name__)

WORKTREE_ROOT = ".mai/worktrees"


async def _git(cmd: str, cwd: str, timeout: float = 30.0) -> tuple[str, str, int]:
    """Run a git command, return (stdout, stderr, returncode)."""
    try:
        process = await asyncio.create_subprocess_shell(
            f"git {cmd}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout,
        )
        out = stdout.decode("utf-8", errors="replace") if stdout else ""
        err = stderr.decode("utf-8", errors="replace") if stderr else ""
        return out, err, process.returncode or 0
    except asyncio.TimeoutError:
        return "", "timeout", -1
    except FileNotFoundError:
        return "", "git not found", -1
    except Exception as exc:
        return "", str(exc), -1


def _worktree_path(cwd: str, name: str) -> Path:
    return Path(cwd) / WORKTREE_ROOT / name


def _default_branch(cwd: str) -> str:
    """Best-effort detect default branch (main / master)."""
    out, _, _ = _git_sync("symbolic-ref refs/remotes/origin/HEAD --short", cwd)
    if out.strip():
        return out.strip().replace("origin/", "")
    # Fallback: probe main then master
    for cand in ("main", "master"):
        o, _, c = _git_sync(f"rev-parse --verify {cand}", cwd)
        if c == 0:
            return cand
    return "main"


def _git_sync(cmd: str, cwd: str) -> tuple[str, str, int]:
    """Synchronous git (for quick lookups inside async tools)."""
    import subprocess
    try:
        result = subprocess.run(
            f"git {cmd}",
            shell=True, capture_output=True, text=True, timeout=10, cwd=cwd,
        )
        return result.stdout, result.stderr, result.returncode
    except Exception as exc:
        return "", str(exc), -1


def _validate_name(name: str) -> str:
    """Sanitize worktree name — only allow safe path segments."""
    import re
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-")
    if not cleaned:
        raise ValueError("无效 worktree 名称")
    return cleaned


# ── EnterWorktree ─────────────────────────────────────────


class EnterWorktreeInput(ToolInput):
    name: Optional[str] = Field(
        default=None,
        description="新 worktree 名称（省略则随机生成）。仅允许字母数字 . _ -",
    )
    path: Optional[str] = Field(
        default=None,
        description="进入已存在的 worktree 路径（用于切换而非创建）",
    )
    base_ref: str = Field(
        default="head",
        description="创建基准: head(当前 HEAD) | fresh(origin/default 分支)",
    )


class EnterWorktreeTool(Tool):
    """创建/进入 git worktree，切换会话工作目录到隔离副本。

    Claude Code 对应物: EnterWorktree。
    """
    name = "EnterWorktree"
    description = (
        "创建一个隔离的 git worktree（独立分支 + 独立文件系统副本）并切换会话工作目录到它。"
        "用于在不影响主工作区的情况下试验性修改代码。"
    )
    input_schema = EnterWorktreeInput
    is_concurrency_safe = False

    async def call(self, input: EnterWorktreeInput, context: RunContext) -> str:
        cwd = context.cwd
        stack = context.session_state.setdefault("worktree_stack", [])

        # 校验当前目录是 git 仓库
        _, _, code = await _git("rev-parse --is-inside-work-tree", cwd)
        if code != 0:
            return "[ERROR] 当前目录不是 git 仓库，无法创建 worktree"

        # 切换到已存在 worktree
        if input.path:
            target = Path(input.path).resolve()
            if not target.is_dir():
                return f"[ERROR] 路径不存在: {target}"
            stack.append(cwd)
            context.cwd = str(target)
            logger.info("进入已有 worktree: %s", target)
            return f"已切换到 worktree: {target}"

        # 创建新 worktree
        name = _validate_name(input.name) if input.name else f"wt-{len(stack)+1}"
        wt_path = _worktree_path(cwd, name)
        if wt_path.exists():
            return f"[ERROR] worktree 已存在: {wt_path}"

        branch = f"mai/{name}"

        if input.base_ref == "fresh":
            base = _default_branch(cwd)
            # 从 origin/<default> 创建新分支
            cmd = f'worktree add -b "{branch}" "{wt_path}" "origin/{base}"'
        else:
            cmd = f'worktree add -b "{branch}" "{wt_path}" HEAD'

        out, err, rc = await _git(cmd, cwd)
        if rc != 0:
            # fresh 失败时回退到 head
            if input.base_ref == "fresh" and "unknown revision" in err.lower() or "not a valid" in err.lower():
                cmd = f'worktree add -b "{branch}" "{wt_path}" HEAD'
                out, err, rc = await _git(cmd, cwd)
            if rc != 0:
                return f"[ERROR] 创建 worktree 失败: {err.strip() or out.strip()}"

        # 记录原 cwd，切换会话工作目录
        stack.append(cwd)
        context.cwd = str(wt_path)
        logger.info("创建 worktree: %s (branch=%s)", wt_path, branch)
        return (
            f"已创建隔离 worktree:\n"
            f"  路径: {wt_path}\n"
            f"  分支: {branch}\n"
            f"  基准: {input.base_ref}\n"
            f"会话工作目录已切换到此 worktree。用 ExitWorktree 返回。"
        )


registry.register(EnterWorktreeTool())


# ── ExitWorktree ──────────────────────────────────────────


class ExitWorktreeInput(ToolInput):
    action: str = Field(
        default="keep",
        description="keep=保留 worktree 与分支 | remove=删除 worktree 与分支",
    )
    discard_changes: bool = Field(
        default=False,
        description="action=remove 时，若有未提交改动是否强制删除（否则拒绝）",
    )


class ExitWorktreeTool(Tool):
    """退出当前 worktree，返回原工作目录。可选保留或移除。

    Claude Code 对应物: ExitWorktree。
    """
    name = "ExitWorktree"
    description = (
        "退出当前 worktree，返回原工作目录。可选择保留 worktree（留待后续）"
        "或移除它（删除分支与目录）。移除时有未提交改动会拒绝，除非 discard_changes=true。"
    )
    input_schema = ExitWorktreeInput
    is_concurrency_safe = False

    async def call(self, input: ExitWorktreeInput, context: RunContext) -> str:
        stack = context.session_state.get("worktree_stack", [])
        if not stack:
            return "[ERROR] 当前不在 worktree 中（栈为空）"

        wt_cwd = context.cwd
        original_cwd = stack.pop()
        context.cwd = original_cwd

        if input.action == "keep":
            return (
                f"已退出 worktree，返回 {original_cwd}\n"
                f"worktree 保留于: {wt_cwd}"
            )

        # action == remove
        if input.action != "remove":
            return f"[ERROR] 未知 action: {input.action}（应为 keep | remove）"

        # 检查是否有未提交改动
        status_out, _, _ = await _git("status --porcelain", wt_cwd)
        has_changes = bool(status_out.strip())

        if has_changes and not input.discard_changes:
            # 把 cwd 还原回去，因为没删成功
            stack.append(original_cwd)
            context.cwd = wt_cwd
            return (
                "[ERROR] worktree 有未提交改动，拒绝删除。"
                "设置 discard_changes=true 强制删除。"
            )

        # 获取分支名以删除
        branch_out, _, _ = await _git("branch --show-current", wt_cwd)
        branch = branch_out.strip()

        # 移除 worktree
        out, err, rc = await _git(f'worktree remove --force "{wt_cwd}"', original_cwd)
        if rc != 0:
            # force 仍失败则手动删目录
            import shutil
            try:
                shutil.rmtree(wt_cwd, ignore_errors=True)
            except Exception:
                pass

        # 删除分支
        if branch:
            await _git(f'branch -D "{branch}"', original_cwd)

        logger.info("移除 worktree: %s (branch=%s)", wt_cwd, branch)
        return (
            f"已退出并移除 worktree:\n"
            f"  路径: {wt_cwd}\n"
            f"  分支: {branch or '(detached)'}\n"
            f"返回: {original_cwd}"
        )


registry.register(ExitWorktreeTool())


# ── ListWorktrees (辅助) ─────────────────────────────────


class ListWorktreesInput(ToolInput):
    pass


class ListWorktreesTool(Tool):
    """列出当前仓库所有 git worktree。"""
    name = "ListWorktrees"
    description = "列出当前 git 仓库的所有 worktree（主 + 副本）。"
    input_schema = ListWorktreesInput
    is_concurrency_safe = True

    async def call(self, input: ListWorktreesInput, context: RunContext) -> str:
        out, err, rc = await _git("worktree list", context.cwd)
        if rc != 0:
            return f"[ERROR] {err.strip()}"
        return out.strip() or "(无 worktree)"


registry.register(ListWorktreesTool())
