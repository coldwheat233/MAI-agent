"""NotebookEdit — 对应 Claude Code 的 NotebookEditTool。

编辑 Jupyter notebook (.ipynb) 的单元格。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry
from mai_agent.tools.utils import resolve_path


class NotebookEditInput(ToolInput):
    notebook_path: str = Field(description="notebook 文件的绝对路径 (.ipynb)")
    new_source: str = Field(description="单元格的新内容")
    cell_id: Optional[str] = Field(default=None, description="要替换/删除的单元格 ID")
    cell_type: str = Field(default="code", description="新单元格类型: code | markdown")
    edit_mode: str = Field(default="replace", description="操作模式: replace | insert | delete")


class NotebookEditTool(Tool):
    """编辑 Jupyter notebook 单元格。

    Claude Code 对应物: NotebookEditTool。
    - replace: 替换指定 cell_id 的内容
    - insert: 在指定 cell_id 后插入新单元格
    - delete: 删除指定 cell_id
    """
    name = "NotebookEdit"
    description = "编辑 Jupyter notebook (.ipynb) 的单元格。支持替换/插入/删除。"
    input_schema = NotebookEditInput
    is_concurrency_safe = False

    async def call(self, input: NotebookEditInput, context: RunContext) -> str:
        path = resolve_path(input.notebook_path, context.cwd)

        if not path.exists():
            return f"[ERROR] Notebook not found: {path}"

        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return f"[ERROR] Invalid notebook JSON: {e}"

        cells = nb.get("cells", [])

        if input.edit_mode == "replace":
            if not input.cell_id:
                return "[ERROR] cell_id required for replace mode"
            found = False
            for c in cells:
                if c.get("id") == input.cell_id:
                    c["source"] = _split_source(input.new_source)
                    c["cell_type"] = input.cell_type
                    found = True
                    break
            if not found:
                return f"[ERROR] Cell {input.cell_id} not found"

        elif input.edit_mode == "insert":
            new_id = str(len(cells) + 1).zfill(8)
            new_cell = {
                "id": new_id,
                "cell_type": input.cell_type,
                "source": _split_source(input.new_source),
                "metadata": {},
            }
            if input.cell_id:
                for i, c in enumerate(cells):
                    if c.get("id") == input.cell_id:
                        cells.insert(i + 1, new_cell)
                        break
                else:
                    cells.append(new_cell)
            else:
                cells.insert(0, new_cell)

        elif input.edit_mode == "delete":
            if not input.cell_id:
                return "[ERROR] cell_id required for delete mode"
            nb["cells"] = [c for c in cells if c.get("id") != input.cell_id]

        else:
            return f"[ERROR] Unknown edit_mode: {input.edit_mode}"

        nb["cells"] = cells
        path.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
        return f"Notebook updated: {path} ({len(nb['cells'])} cells, mode={input.edit_mode})"


def _split_source(text: str) -> list[str]:
    """Split source text into lines (Jupyter format)."""
    if "\n" in text:
        lines = text.splitlines(True)
        if not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        return lines
    return [text + "\n"]


registry.register(NotebookEditTool())
