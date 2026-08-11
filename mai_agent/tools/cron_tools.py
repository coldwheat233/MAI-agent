"""Cron 系列工具 — 对应 Claude Code 的 CronCreate/CronDelete/CronList。

定时/延迟触发任务的能力。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry

CRON_FILE = ".mai/cron.json"


def _cron_path(cwd: str) -> Path:
    return Path(cwd) / CRON_FILE


def _load(cwd: str) -> list[dict]:
    p = _cron_path(cwd)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def _save(cwd: str, data: list[dict]) -> None:
    p = _cron_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── CronCreate ─────────────────────────────────────────────


class CronCreateInput(ToolInput):
    cron: str = Field(description="5字段cron表达式 (min hour dom month dow). 如 '0 9 * * *' = 每天9点")
    prompt: str = Field(description="触发时要执行的任务描述")
    recurring: bool = Field(default=True, description="是否重复执行")
    durable: bool = Field(default=False, description="是否跨会话持久化")


class CronCreateTool(Tool):
    name = "CronCreate"
    description = "创建定时任务。支持标准5字段cron表达式。如 '*/5 * * * *' 每5分钟, '0 9 * * 1-5' 工作日9点。"
    input_schema = CronCreateInput
    is_concurrency_safe = False

    async def call(self, input: CronCreateInput, context: RunContext) -> str:
        jobs = _load(context.cwd)
        # Validate cron
        fields = input.cron.strip().split()
        if len(fields) != 5:
            return f"[ERROR] Invalid cron expression: {input.cron}. Expected 5 fields."
        jid = f"cron_{len(jobs) + 1:03d}"
        job = {
            "id": jid,
            "cron": input.cron,
            "prompt": input.prompt,
            "recurring": input.recurring,
            "durable": input.durable,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        jobs.append(job)
        _save(context.cwd, jobs)
        rec = " (recurring)" if input.recurring else " (once)"
        return f"Cron job #{jid} created: {input.cron}{rec} — {input.prompt[:60]}"


registry.register(CronCreateTool())


# ── CronDelete ─────────────────────────────────────────────


class CronDeleteInput(ToolInput):
    id: str = Field(description="要删除的定时任务 ID（如 cron_001）")


class CronDeleteTool(Tool):
    name = "CronDelete"
    description = "删除一个定时任务。"
    input_schema = CronDeleteInput
    is_concurrency_safe = False

    async def call(self, input: CronDeleteInput, context: RunContext) -> str:
        jobs = _load(context.cwd)
        before = len(jobs)
        jobs = [j for j in jobs if j["id"] != input.id]
        if len(jobs) == before:
            return f"[ERROR] Cron job #{input.id} not found"
        _save(context.cwd, jobs)
        return f"Cron job #{input.id} deleted ({len(jobs)} remaining)"


registry.register(CronDeleteTool())


# ── CronList ───────────────────────────────────────────────


class CronListInput(ToolInput):
    pass  # No params needed


class CronListTool(Tool):
    name = "CronList"
    description = "列出所有已注册的定时任务。"
    input_schema = CronListInput
    is_concurrency_safe = True

    async def call(self, input: CronListInput, context: RunContext) -> str:
        jobs = _load(context.cwd)
        if not jobs:
            return "No cron jobs."
        lines = []
        for j in jobs:
            rec = "↻" if j.get("recurring") else "→"
            dur = "💾" if j.get("durable") else ""
            lines.append(f"  {rec} #{j['id']} {j['cron']} {dur} {j['prompt'][:60]}")
        return "\n".join(lines)


registry.register(CronListTool())
