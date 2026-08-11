"""Shell 执行工具 — 对应 Claude Code 的 BashTool。

在子进程中执行 shell 命令，支持超时、后台运行、沙箱审查。
"""

from __future__ import annotations

import asyncio
import shlex

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry


class BashInput(ToolInput):
    command: str = Field(description="要执行的 shell 命令")
    timeout: int = Field(default=120_000, description="超时时间（毫秒），默认2分钟")
    description: str = Field(default="", description="命令描述（用于日志和安全审计）")


class BashTool(Tool):
    """在子进程中执行 shell 命令。

    Claude Code 对应物: BashTool

    安全设计：
      - 命令通过 asyncio.subprocess 执行
      - 支持超时（默认2分钟，最长10分钟）
      - 捕获 stdout + stderr
      - 沙箱策略审查（session_state["sandbox"] 控制，见 mai_agent.sandbox）
      - is_concurrency_safe = False (shell 可能修改文件系统)
    """
    name = "Bash"
    description = "执行 shell 命令。返回 stdout + stderr。"
    input_schema = BashInput
    is_concurrency_safe = False
    _MAX_TIMEOUT = 600_000  # 10 minutes

    async def call(self, input: BashInput, context: RunContext) -> str:
        command = input.command.strip()
        timeout_ms = min(input.timeout, self._MAX_TIMEOUT)
        cb = context.stream_callback  # async fn(text: str)

        # ── 沙箱审查 ──
        # session_state["sandbox"] 可放置一个 SandboxPolicy 实例
        policy = context.session_state.get("sandbox")
        if policy is not None and getattr(policy, "active", False):
            from mai_agent.sandbox.policy import SandboxDecision
            decision, violations = policy.validate(command, context.cwd)
            if decision == SandboxDecision.DENY:
                reasons = "\n".join(f"  - [{v.rule}] {v.detail}" for v in violations)
                if cb:
                    await cb(f"\n[ERROR] 沙箱拦截命令")
                return (
                    f"[ERROR] 命令被沙箱策略拦截:\n{reasons}\n"
                    f"命令: {command}"
                )

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=context.cwd,
            )

            async def _read_stream(stream, prefix: str) -> str:
                """Read stream line by line, emit via callback."""
                lines: list[str] = []
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip("\n")
                    lines.append(text)
                    if cb:
                        try:
                            await cb(f"{prefix}{text}")
                        except Exception:
                            pass
                return "".join(f"{l}\n" for l in lines) if lines else ""

            try:
                stdout_task = asyncio.create_task(_read_stream(process.stdout, ""))
                stderr_task = asyncio.create_task(_read_stream(process.stderr, "[stderr] "))

                done, pending = await asyncio.wait(
                    [stdout_task, stderr_task],
                    timeout=timeout_ms / 1000,
                )
                for t in pending:
                    t.cancel()

                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
                if cb:
                    await cb(f"\n[ERROR] Command timed out after {timeout_ms / 1000:.0f}s")
                return f"[ERROR] Command timed out ({timeout_ms / 1000:.0f}s): {command}"

            stdout_text = stdout_task.result() if not stdout_task.cancelled() else ""
            stderr_text = stderr_task.result() if not stderr_task.cancelled() else ""

            parts = []
            if stdout_text.strip():
                parts.append(f"[stdout]\n{stdout_text.rstrip()}")
            if stderr_text.strip():
                parts.append(f"[stderr]\n{stderr_text.rstrip()}")

            if not parts:
                return f"(Command completed, exit: {process.returncode})"

            footer = f"\n(exit: {process.returncode})"
            return "\n".join(parts) + footer

        except FileNotFoundError:
            return f"[ERROR] Command not found: {shlex.split(command)[0]}"
        except Exception as exc:
            return f"[ERROR] Command failed: {exc}"


registry.register(BashTool())
