"""文件模式匹配工具 — 对应 Claude Code 的 GlobTool。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry


class GlobInput(ToolInput):
    pattern: str = Field(description="文件匹配模式，如 '**/*.py' 或 'src/**/*.ts'")
    path: Optional[str] = Field(default=None, description="搜索根目录，默认为当前工作目录")


class GlobTool(Tool):
    """按 glob 模式匹配文件路径。

    Claude Code 对应物: GlobTool
    is_concurrency_safe = True (只读)
    """
    name = "Glob"
    description = "按 glob 模式查找文件。支持 ** 递归匹配。返回匹配的文件路径列表。"
    input_schema = GlobInput
    is_concurrency_safe = True

    async def call(self, input: GlobInput, context: RunContext) -> str:
        root = Path(input.path or context.cwd)
        if not root.exists():
            return f"[ERROR] 路径不存在: {root}"

        matches = sorted(root.glob(input.pattern))
        # 限制返回数量
        if len(matches) > 200:
            matches = matches[:200]
            trunc_msg = f"\n... (已截断，共匹配 {len(matches)} 个文件，仅显示前 200 个)"
        else:
            trunc_msg = ""

        if not matches:
            return f"没有匹配 '{input.pattern}' 的文件。"

        lines = [str(m.relative_to(root)) for m in matches]
        return "\n".join(lines) + trunc_msg


registry.register(GlobTool())
