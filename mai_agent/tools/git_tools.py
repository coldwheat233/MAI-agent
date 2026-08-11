"""Git tools — status, diff, commit, log.

All tools wrap git CLI via subprocess. In manual mode, GitCommit shows
diff and asks for confirmation before committing.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry


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


# ── GitStatus ─────────────────────────────────────────────


class GitStatusInput(ToolInput):
    """No parameters needed — shows status of current repo."""


class GitStatusTool(Tool):
    name = "GitStatus"
    description = "Show git status (branch, staged/unstaged changes, untracked files)."
    input_schema = GitStatusInput
    is_concurrency_safe = True

    async def call(self, input: GitStatusInput, context: RunContext) -> str:
        branch_out, _, _ = await _git("branch --show-current", context.cwd)
        status_out, _, _ = await _git("status --short", context.cwd)

        branch = branch_out.strip() or "(detached)"
        if not status_out.strip():
            return f"Branch: {branch}\nWorking tree clean."

        return f"Branch: {branch}\n\n{status_out.strip()}"


registry.register(GitStatusTool())


# ── GitDiff ───────────────────────────────────────────────


class GitDiffInput(ToolInput):
    staged: bool = Field(default=False, description="Show staged diff instead of unstaged")


class GitDiffTool(Tool):
    name = "GitDiff"
    description = "Show git diff (unstaged by default, --staged for staged changes)."
    input_schema = GitDiffInput
    is_concurrency_safe = True

    async def call(self, input: GitDiffInput, context: RunContext) -> str:
        flag = "--staged" if input.staged else ""
        out, err, code = await _git(f"diff {flag} --stat", context.cwd)
        if not out.strip():
            return "No changes to show."

        # Get actual diff (truncated)
        diff_out, _, _ = await _git(f"diff {flag}", context.cwd)
        summary = out.strip()
        detail = diff_out[:3000] if len(diff_out) > 3000 else diff_out
        if len(diff_out) > 3000:
            detail += "\n... (truncated)"

        return f"{summary}\n\n{detail}"


registry.register(GitDiffTool())


# ── GitCommit ─────────────────────────────────────────────


class GitCommitInput(ToolInput):
    message: str = Field(description="Commit message")
    files: Optional[list[str]] = Field(default=None, description="Optional: specific files to add (default: all)")
    auto_stage: bool = Field(default=True, description="Run git add before commit")


class GitCommitTool(Tool):
    """Git commit — in manual mode, the permission gate shows diff first.

    Claude Code pattern: the tool itself doesn't ask — the permission hook does.
    """
    name = "GitCommit"
    description = "Commit changes to git. Add files, commit with message."
    input_schema = GitCommitInput
    is_concurrency_safe = False

    async def call(self, input: GitCommitInput, context: RunContext) -> str:
        # Stage
        if input.auto_stage:
            if input.files:
                for f in input.files:
                    await _git(f'add "{f}"', context.cwd)
            else:
                await _git("add -A", context.cwd)

        # Check if anything to commit
        out, _, _ = await _git("diff --cached --stat", context.cwd)
        if not out.strip():
            return "Nothing to commit (no staged changes)."

        # Commit
        msg = input.message.replace('"', '\\"')
        stdout, stderr, code = await _git(f'commit -m "{msg}"', context.cwd)

        if code != 0:
            return f"[ERROR] Commit failed: {stderr}"

        # Get the commit hash
        hash_out, _, _ = await _git("log -1 --oneline", context.cwd)
        return f"Committed: {hash_out.strip()}"


registry.register(GitCommitTool())


# ── GitLog ────────────────────────────────────────────────


class GitLogInput(ToolInput):
    count: int = Field(default=10, description="Number of commits to show")
    oneline: bool = Field(default=True, description="One line per commit")


class GitLogTool(Tool):
    name = "GitLog"
    description = "Show recent git commit history."
    input_schema = GitLogInput
    is_concurrency_safe = True

    async def call(self, input: GitLogInput, context: RunContext) -> str:
        flag = "--oneline" if input.oneline else ""
        out, _, _ = await _git(f"log {flag} -n {input.count}", context.cwd)
        return out.strip() or "No commits yet."


registry.register(GitLogTool())


# ── GitPush ───────────────────────────────────────────────


class GitPushInput(ToolInput):
    remote: str = Field(default="origin", description="远程仓库名")
    branch: Optional[str] = Field(default=None, description="分支名（默认当前分支）")
    force: bool = Field(default=False, description="强制推送 (--force)")


class GitPushTool(Tool):
    """Git push — 推送本地提交到远程仓库。"""
    name = "GitPush"
    description = "Push commits to a remote repository. Default: origin + current branch."
    input_schema = GitPushInput
    is_concurrency_safe = False

    async def call(self, input: GitPushInput, context: RunContext) -> str:
        branch_flag = input.branch or ""
        force_flag = "--force" if input.force else ""
        cmd = f"push {input.remote} {branch_flag} {force_flag}".strip()
        out, err, code = await _git(cmd, context.cwd)

        if code != 0:
            return f"[ERROR] Push failed: {err or out}"
        return out.strip() or "Push successful."


registry.register(GitPushTool())


# ── GitPull ───────────────────────────────────────────────


class GitPullInput(ToolInput):
    remote: str = Field(default="origin", description="远程仓库名")
    branch: Optional[str] = Field(default=None, description="分支名（默认当前分支）")
    rebase: bool = Field(default=False, description="使用 rebase 而非 merge (--rebase)")


class GitPullTool(Tool):
    """Git pull — 从远程仓库拉取更新。"""
    name = "GitPull"
    description = "Pull latest changes from a remote repository. Default: origin + current branch."
    input_schema = GitPullInput
    is_concurrency_safe = False

    async def call(self, input: GitPullInput, context: RunContext) -> str:
        flags = "--rebase" if input.rebase else ""
        branch = input.branch or ""
        cmd = f"pull {input.remote} {branch} {flags}".strip()
        out, err, code = await _git(cmd, context.cwd)

        if code != 0:
            return f"[ERROR] Pull failed: {err or out}"
        return out.strip() or "Already up to date."


registry.register(GitPullTool())


# ── GitClone ──────────────────────────────────────────────


class GitCloneInput(ToolInput):
    url: str = Field(description="仓库 URL（HTTPS 或 SSH）")
    target_dir: Optional[str] = Field(default=None, description="目标目录（默认使用仓库名）")
    branch: Optional[str] = Field(default=None, description="克隆后切换到指定分支")
    depth: int = Field(default=0, description="浅克隆深度（0=完整克隆）")


class GitCloneTool(Tool):
    """Git clone — 克隆远程仓库到本地。"""
    name = "GitClone"
    description = "Clone a remote git repository to a local directory."
    input_schema = GitCloneInput
    is_concurrency_safe = False

    async def call(self, input: GitCloneInput, context: RunContext) -> str:
        parts = ["clone"]
        if input.depth > 0:
            parts.append(f"--depth {input.depth}")
        if input.branch:
            parts.append(f"--branch {input.branch}")
        parts.append(input.url)
        if input.target_dir:
            parts.append(input.target_dir)
        cmd = " ".join(parts)
        out, err, code = await _git(cmd, context.cwd)

        if code != 0:
            return f"[ERROR] Clone failed: {err or out}"
        return out.strip() or "Clone successful."


registry.register(GitCloneTool())


# ── GitRemote ─────────────────────────────────────────────


class GitRemoteInput(ToolInput):
    action: str = Field(default="list", description="list | add | remove")
    name: Optional[str] = Field(default=None, description="远程仓库名（add/remove 时必填）")
    url: Optional[str] = Field(default=None, description="远程仓库 URL（add 时必填）")


class GitRemoteTool(Tool):
    """Git remote — 管理远程仓库地址。"""
    name = "GitRemote"
    description = "Manage git remotes: list, add, or remove remote repositories."
    input_schema = GitRemoteInput
    is_concurrency_safe = True if False else False  # list 是只读的

    async def call(self, input: GitRemoteInput, context: RunContext) -> str:
        if input.action == "list":
            out, _, _ = await _git("remote -v", context.cwd)
            return out.strip() or "No remotes configured."
        elif input.action == "add":
            if not input.name or not input.url:
                return "[ERROR] add 需要 name 和 url 参数"
            out, err, code = await _git(f'remote add {input.name} {input.url}', context.cwd)
            return f"Remote '{input.name}' added." if code == 0 else f"[ERROR] {err or out}"
        elif input.action == "remove":
            if not input.name:
                return "[ERROR] remove 需要 name 参数"
            out, err, code = await _git(f'remote remove {input.name}', context.cwd)
            return f"Remote '{input.name}' removed." if code == 0 else f"[ERROR] {err or out}"
        else:
            return f"[ERROR] 未知操作: {input.action}（应为 list | add | remove）"


registry.register(GitRemoteTool())
