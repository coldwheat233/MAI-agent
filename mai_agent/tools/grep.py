"""内容搜索工具 — 对应 Claude Code 的 GrepTool。

基于 ripgrep 的内容搜索，支持正则表达式。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry


class GrepInput(ToolInput):
    pattern: str = Field(description="要搜索的正则表达式模式")
    path: Optional[str] = Field(default=None, description="搜索目录，默认为当前工作目录")
    glob: Optional[str] = Field(default=None, description="文件名过滤通配符，如 '*.py'")
    output_mode: str = Field(
        default="content",
        description="输出模式: 'content'(匹配行), 'files_with_matches'(文件路径), 'count'(计数)"
    )
    head_limit: int = Field(default=250, description="最大输出行数")
    ignore_case: bool = Field(default=False, description="是否忽略大小写")


class GrepTool(Tool):
    """基于 ripgrep 的内容搜索。

    Claude Code 对应物: GrepTool

    使用 subprocess 调用系统 rg 命令。如果 rg 不可用，回退到 Python 纯文本搜索。
    is_concurrency_safe = True (只读)
    """
    name = "Grep"
    description = "使用正则表达式在文件中搜索内容。支持通配符过滤和多种输出模式。"
    input_schema = GrepInput
    is_concurrency_safe = True

    async def call(self, input: GrepInput, context: RunContext) -> str:
        try:
            return await self._rg_search(input, context)
        except (FileNotFoundError, Exception):
            return await self._python_search(input, context)

    async def _rg_search(self, input: GrepInput, context: RunContext) -> str:
        """使用 ripgrep"""
        search_path = input.path or context.cwd
        args = ["rg", "--no-heading", "--line-number"]

        if input.ignore_case:
            args.append("-i")

        if input.glob:
            args.extend(["-g", input.glob])

        if input.output_mode == "files_with_matches":
            args.append("-l")
        elif input.output_mode == "count":
            args.append("-c")

        args.append(input.pattern)
        args.append(str(search_path))

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=context.cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            process.kill()
            return "[ERROR] Grep 搜索超时"

        output = stdout.decode("utf-8", errors="replace")
        if not output.strip():
            return "没有匹配结果。"

        lines = output.splitlines()
        if len(lines) > input.head_limit:
            lines = lines[:input.head_limit]
            lines.append(f"... (已截断，共 {len(lines)} 行)")

        return "\n".join(lines)

    async def _python_search(self, input: GrepInput, context: RunContext) -> str:
        """纯 Python 回退搜索（rg 不可用时）"""
        import re

        search_path = Path(input.path or context.cwd)
        if not search_path.exists():
            return f"[ERROR] 路径不存在: {search_path}"

        pattern = re.compile(input.pattern, re.IGNORECASE if input.ignore_case else 0)

        results: list[str] = []
        search_files = (
            search_path.rglob(input.glob or "*")
            if search_path.is_dir()
            else [search_path]
        )

        matched_files: set[str] = set()

        for f in search_files:
            if not f.is_file():
                continue
            if len(results) > input.head_limit:
                break

            try:
                content = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            for i, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    if input.output_mode == "files_with_matches":
                        matched_files.add(str(f))
                        break
                    elif input.output_mode == "count":
                        pass  # 等会统一计数
                    else:
                        results.append(f"{f}:{i}: {line.rstrip()}")
                        if len(results) >= input.head_limit:
                            break

        if input.output_mode == "files_with_matches":
            return "\n".join(sorted(matched_files)) or "没有匹配结果。"
        elif input.output_mode == "count":
            return f"匹配文件数: {len(matched_files)}, 匹配行数: {len(results)}"

        return "\n".join(results) or "没有匹配结果。"


registry.register(GrepTool())
