"""精确字符串替换工具 — 对应 Claude Code 的 FileEditTool。

对文件做精确的字符串替换，避免简单的 patch/line-based 编辑问题。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry
from mai_agent.tools.utils import resolve_path
from mai_agent.tools.snapshots import save_snapshot


class FileEditInput(ToolInput):
    file_path: str = Field(description="要修改的文件绝对路径")
    old_string: str = Field(description="要被替换的原始文本（必须与文件中完全一致）")
    new_string: str = Field(description="替换后的新文本")
    replace_all: bool = Field(default=False, description="替换所有匹配的 old_string")


class FileEditTool(Tool):
    """精确字符串替换。

    对应 Claude Code 行为:
      - old_string 必须在文件中精确匹配（包括缩进和空白）
      - 如果 old_string 不唯一且 replace_all=False，返回错误
      - replace_all=True 时替换所有匹配
      - is_concurrency_safe = False (写操作)
    """
    name = "Edit"
    description = "对文件做精确字符串替换。old_string 必须与文件内容完全一致（含缩进）。"
    input_schema = FileEditInput
    is_concurrency_safe = False

    async def call(self, input: FileEditInput, context: RunContext) -> str:
        path = resolve_path(input.file_path, context.cwd)

        if not path.exists():
            return f"[ERROR] File not found: {path}"

        content = path.read_text(encoding="utf-8")

        # Snapshot before modifying
        snap_id = save_snapshot(str(path), context.cwd)

        if input.old_string not in content:
            return (
                f"[ERROR] old_string not found in file. "
                f"Verify the text matches exactly (including whitespace)."
            )

        count = content.count(input.old_string)
        if count > 1 and not input.replace_all:
            return (
                f"[ERROR] old_string 在文件中出现了 {count} 次，但 replace_all=False。"
                f"请提供更多上下文使 old_string 唯一，或设置 replace_all=True。"
            )

        if input.replace_all:
            new_content = content.replace(input.old_string, input.new_string)
            replacements = count
        else:
            new_content = content.replace(input.old_string, input.new_string, 1)
            replacements = 1

        path.write_text(new_content, encoding="utf-8")
        diff = _compute_diff(input.old_string, input.new_string)
        snap_msg = f"\n[snapshot: {snap_id}]" if snap_id else ""
        return f"Modified: {path} ({replacements} replacement(s)){snap_msg}\n{diff}"


def _compute_diff(old: str, new: str) -> str:
    """Generate a simple +/- diff for display."""
    old_lines = old.splitlines() or [old]
    new_lines = new.splitlines() or [new]
    lines: list[str] = []
    for ol in old_lines:
        lines.append(f"- {ol}")
    for nl in new_lines:
        lines.append(f"+ {nl}")
    return "\n".join(lines)


registry.register(FileEditTool())
