"""Task 系列工具 — 对应 Claude Code 的 TaskCreate/TaskUpdate/TaskGet/TaskList/TaskOutput/TaskStop。

管理后台任务（shell、子Agent、部署）的生命周期。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry

TASK_DIR = ".mai/tasks"


def _task_file(cwd: str) -> Path:
    return Path(cwd) / TASK_DIR / "tasks.json"


def _load_tasks(cwd: str) -> list[dict]:
    f = _task_file(cwd)
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return []


def _save_tasks(cwd: str, tasks: list[dict]) -> None:
    f = _task_file(cwd)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


# ── TaskCreate ────────────────────────────────────────────


class TaskCreateInput(ToolInput):
    subject: str = Field(description="任务标题")
    description: str = Field(description="任务描述")


class TaskCreateTool(Tool):
    name = "TaskCreate"
    description = "创建一个后台任务。用于追踪需要异步执行的工作。"
    input_schema = TaskCreateInput
    is_concurrency_safe = False

    async def call(self, input: TaskCreateInput, context: RunContext) -> str:
        tasks = _load_tasks(context.cwd)
        tid = str(len(tasks) + 1).zfill(3)
        task = {
            "id": tid,
            "subject": input.subject,
            "description": input.description,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        tasks.append(task)
        _save_tasks(context.cwd, tasks)
        return f"Task #{tid} created: {input.subject}"


registry.register(TaskCreateTool())


# ── TaskUpdate ────────────────────────────────────────────


class TaskUpdateInput(ToolInput):
    task_id: str = Field(description="任务 ID（如 #001）")
    status: str = Field(description="新状态: pending | in_progress | completed | deleted")
    subject: Optional[str] = Field(default=None, description="可选: 更新标题")
    description: Optional[str] = Field(default=None, description="可选: 更新描述")


class TaskUpdateTool(Tool):
    name = "TaskUpdate"
    description = "更新后台任务的状态或内容。"
    input_schema = TaskUpdateInput
    is_concurrency_safe = False

    async def call(self, input: TaskUpdateInput, context: RunContext) -> str:
        tasks = _load_tasks(context.cwd)
        tid = input.task_id.lstrip("#")
        for t in tasks:
            if t["id"] == tid:
                t["status"] = input.status
                if input.subject:
                    t["subject"] = input.subject
                if input.description:
                    t["description"] = input.description
                _save_tasks(context.cwd, tasks)
                return f"Task #{tid} updated: {t['status']}"
        return f"[ERROR] Task #{tid} not found"


registry.register(TaskUpdateTool())


# ── TaskList ──────────────────────────────────────────────


class TaskListInput(ToolInput):
    status: Optional[str] = Field(default=None, description="可选: 按状态过滤 (pending|in_progress|completed)")


class TaskListTool(Tool):
    name = "TaskList"
    description = "列出所有后台任务及其状态。"
    input_schema = TaskListInput
    is_concurrency_safe = True

    async def call(self, input: TaskListInput, context: RunContext) -> str:
        tasks = _load_tasks(context.cwd)
        if input.status:
            tasks = [t for t in tasks if t["status"] == input.status]
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            icon = {"pending": "○", "in_progress": "●", "completed": "✓", "deleted": "✗"}.get(t["status"], "?")
            lines.append(f"  [{icon}] #{t['id']} {t['subject']} ({t['status']})")
        return "\n".join(lines)


registry.register(TaskListTool())


# ── TaskGet ───────────────────────────────────────────────


class TaskGetInput(ToolInput):
    task_id: str = Field(description="任务 ID（如 #001）")


class TaskGetTool(Tool):
    name = "TaskGet"
    description = "获取单个任务的详细信息。"
    input_schema = TaskGetInput
    is_concurrency_safe = True

    async def call(self, input: TaskGetInput, context: RunContext) -> str:
        tasks = _load_tasks(context.cwd)
        tid = input.task_id.lstrip("#")
        for t in tasks:
            if t["id"] == tid:
                return json.dumps(t, ensure_ascii=False, indent=2)
        return f"[ERROR] Task #{tid} not found"


registry.register(TaskGetTool())


# ── TaskOutput ────────────────────────────────────────────


class TaskOutputInput(ToolInput):
    task_id: str = Field(description="任务 ID（如 #001）")
    block: bool = Field(default=True, description="是否等待任务完成")
    timeout: int = Field(default=30000, description="等待超时（毫秒）")


class TaskOutputTool(Tool):
    """读取后台任务的输出文件。对应 Claude Code 的 TaskOutputTool。"""
    name = "TaskOutput"
    description = "读取后台 Shell/Agent 任务的输出。可阻塞等待任务完成。"
    input_schema = TaskOutputInput
    is_concurrency_safe = True

    async def call(self, input: TaskOutputInput, context: RunContext) -> str:
        tid = input.task_id.lstrip("#")
        out_file = Path(context.cwd) / TASK_DIR / f"output_{tid}.txt"

        if input.block:
            waited = 0
            while not out_file.exists() and waited < input.timeout / 1000:
                await asyncio.sleep(0.5)
                waited += 0.5
            if not out_file.exists():
                return f"[ERROR] Task #{tid} output not found (waited {waited:.0f}s)"

        if not out_file.exists():
            return f"Task #{tid}: no output yet."

        content = out_file.read_text(encoding="utf-8")
        return f"[Task #{tid} output]\n{content[-4000:]}"  # Last 4K chars


registry.register(TaskOutputTool())


# ── TaskStop ──────────────────────────────────────────────


class TaskStopInput(ToolInput):
    task_id: str = Field(description="任务 ID（如 #001）")


class TaskStopTool(Tool):
    name = "TaskStop"
    description = "停止一个运行中的后台任务。"
    input_schema = TaskStopInput
    is_concurrency_safe = False

    async def call(self, input: TaskStopInput, context: RunContext) -> str:
        tasks = _load_tasks(context.cwd)
        tid = input.task_id.lstrip("#")
        for t in tasks:
            if t["id"] == tid:
                t["status"] = "deleted"
                _save_tasks(context.cwd, tasks)
                return f"Task #{tid} stopped."
        return f"[ERROR] Task #{tid} not found"


registry.register(TaskStopTool())
