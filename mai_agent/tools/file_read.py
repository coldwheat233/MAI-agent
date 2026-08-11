"""文件读取工具 — 对应 Claude Code 的 FileReadTool。

支持按行偏移读取、整文件读取。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry
from mai_agent.tools.utils import resolve_path


class FileReadInput(ToolInput):
    file_path: str = Field(description="要读取的文件绝对路径")
    offset: Optional[int] = Field(default=None, description="起始行号 (1-indexed)")
    limit: Optional[int] = Field(default=None, description="读取行数")


class FileReadTool(Tool):
    """读取文件内容。

    对应 Claude Code 行为:
      - 返回内容时带行号（cat -n 格式）
      - 支持偏移和限制，用于大文件分页
      - 读取目录或不存在文件返回错误
      - is_concurrency_safe = True (只读)
    """
    name = "Read"
    description = "从本地文件系统读取文件。支持按行偏移读取。读取目录返回错误。"
    input_schema = FileReadInput
    is_concurrency_safe = True

    async def call(self, input: FileReadInput, context: RunContext) -> str:
        path = resolve_path(input.file_path, context.cwd)

        if not path.exists():
            return f"[ERROR] File not found: {path}"

        if path.is_dir():
            return f"[ERROR] 路径是目录，不是文件: {path}"

        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return f"[ERROR] 无法以 UTF-8 解码文件: {path}"

        total_lines = len(lines)
        start = max(0, (input.offset or 1) - 1)
        end = start + (input.limit or len(lines))

        selected = lines[start:end]
        # cat -n 格式 (对应 Claude Code 的 Read tool 输出格式)
        output_lines = [f"{start + i + 1:>6}\t{line}" for i, line in enumerate(selected)]
        return "\n".join(output_lines)


registry.register(FileReadTool())
