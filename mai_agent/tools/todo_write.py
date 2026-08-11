"""TodoWrite — 对应 Claude Code 的 TodoWriteTool。

让模型能写待办清单，防止长任务中遗忘步骤。
文件持久化到 .mai/todo.md。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry

TODO_FILE = ".mai/todo.md"


class TodoWriteInput(ToolInput):
    content: str = Field(description="Markdown 格式的待办清单内容。使用 - [ ] 和 - [x] 标记。")


class TodoWriteTool(Tool):
    name = "TodoWrite"
    description = "写入/更新待办清单。用于在长任务中跟踪进度，防止遗忘步骤。"
    input_schema = TodoWriteInput
    is_concurrency_safe = False

    async def call(self, input: TodoWriteInput, context: RunContext) -> str:
        path = Path(context.cwd) / TODO_FILE
        path.parent.mkdir(parents=True, exist_ok=True)

        items = [l.strip() for l in input.content.splitlines() if l.strip()]
        done = sum(1 for l in items if l.startswith("- [x]"))
        total = sum(1 for l in items if l.startswith("- ["))

        path.write_text(input.content, encoding="utf-8")
        return f"Todo updated: {done}/{total} done\n{input.content}"


registry.register(TodoWriteTool())
