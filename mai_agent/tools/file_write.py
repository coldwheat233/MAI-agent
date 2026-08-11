"""文件覆写工具 — 对应 Claude Code 的 FileWriteTool。

创建新文件或完全覆盖已有文件。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry
from mai_agent.tools.utils import resolve_path
from mai_agent.tools.snapshots import save_snapshot


class FileWriteInput(ToolInput):
    file_path: str = Field(description="要写入的文件绝对路径")
    content: str = Field(description="要写入的文件内容")


class FileWriteTool(Tool):
    """创建或覆写文件。

    对应 Claude Code 行为:
      - 路径必须是绝对路径
      - 自动创建父目录
      - 如文件已存在则完全覆盖
      - is_concurrency_safe = False (写操作)
    """
    name = "Write"
    description = "写入文件（创建或覆写）。会自动创建父目录。"
    input_schema = FileWriteInput
    is_concurrency_safe = False

    async def call(self, input: FileWriteInput, context: RunContext) -> str:
        path = resolve_path(input.file_path, context.cwd)
        snap_id = save_snapshot(str(path), context.cwd) if path.exists() else ""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(input.content, encoding="utf-8")
        size = len(input.content.encode("utf-8"))
        snap_msg = f"\n[snapshot: {snap_id}]" if snap_id else ""
        return f"Written: {path} ({len(input.content.splitlines())} lines, {_format_size(size)}){snap_msg}"


def _format_size(bytes_count: int) -> str:
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    else:
        return f"{bytes_count / (1024 * 1024):.1f} MB"


registry.register(FileWriteTool())
