"""Workflow Tool — 并行多 Agent 协作。

支持 fan-out 模式：一个任务拆成 N 个子任务，并行执行，汇总结果。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry

logger = logging.getLogger(__name__)


class WorkflowInput(ToolInput):
    tasks: str = Field(description="JSON 数组，每个元素 {prompt: str, tools: [str]}。tools 是允许的工具名列表")
    mode: str = Field(default="parallel", description="parallel (并发) | sequential (串行)")
    max_concurrent: int = Field(default=4, description="最大并发数")


class WorkflowTool(Tool):
    """并行执行多个子 Agent 任务并汇总结果。

    Claude Code 对应物: Workflow 系统 (pipeline/parallel)。

    用法:
        Workflow(tasks=[
            {"prompt": "分析 app.py 的架构", "tools": ["Read", "Grep"]},
            {"prompt": "检查 tests/ 的测试覆盖率", "tools": ["Read", "Glob", "Bash"]},
        ], mode="parallel")
    """
    name = "Workflow"
    description = (
        "并行执行多个子任务，每个子任务有独立的 prompt 和工具白名单。"
        "用于将一个复杂任务拆成多个独立的子分析，并行执行后汇总。"
        "tasks 参数是 JSON 数组: [{\"prompt\": \"...\", \"tools\": [\"Read\", \"Grep\"]}, ...]"
    )
    input_schema = WorkflowInput
    is_concurrency_safe = False

    async def call(self, input: WorkflowInput, context: RunContext) -> str:
        try:
            task_list = json.loads(input.tasks)
        except json.JSONDecodeError as exc:
            return f"[ERROR] 无效的 tasks JSON: {exc}"

        if not isinstance(task_list, list) or len(task_list) == 0:
            return "[ERROR] tasks 必须是非空 JSON 数组"

        # 限制最大任务数
        if len(task_list) > 8:
            return f"[ERROR] 最多 8 个子任务，当前 {len(task_list)}"

        max_conc = min(input.max_concurrent, len(task_list))

        results: list[dict] = []

        if input.mode == "parallel":
            # 并发执行（信号量限流）
            sem = asyncio.Semaphore(max_conc)

            async def run_one(idx: int, task: dict) -> dict:
                async with sem:
                    return await self._run_subtask(idx, task, context)

            coros = [run_one(i, t) for i, t in enumerate(task_list)]
            results = await asyncio.gather(*coros)

        else:
            # 串行执行
            for i, task in enumerate(task_list):
                r = await self._run_subtask(i, task, context)
                results.append(r)

        # 汇总
        lines = [f"Workflow 完成: {len(results)} 个子任务", ""]
        for r in results:
            status = "OK" if r.get("ok") else "FAIL"
            lines.append(f"  [{status}] Task {r['index']}: {r['prompt'][:60]}...")
            if r.get("error"):
                lines.append(f"        Error: {r['error'][:200]}")
            elif r.get("output"):
                lines.append(f"        {r['output'][:300]}")
        return "\n".join(lines)

    async def _run_subtask(self, idx: int, task: dict, context: RunContext) -> dict:
        """运行单个子任务——调 agent_loop 用指定的 tools 白名单。"""
        prompt = task.get("prompt", "")
        allowed = task.get("tools", [])

        if not prompt:
            return {"index": idx, "prompt": "", "ok": False, "error": "Empty prompt"}

        try:
            from mai_agent.llm.client import LLMClient
            from mai_agent.core.loop import agent_loop, AgentLoopConfig

            # 构建子 Agent 上下文：只暴露白名单工具
            sub_context = RunContext(cwd=context.cwd)
            sub_config = AgentLoopConfig(
                max_turns=8,
                system_prompt=(
                    "你是一个子任务执行助手。只使用允许的工具完成任务。\n"
                    "完成后直接输出结果，不要再调用工具。"
                ),
            )

            # 创建临时注册表，只包含允许的工具
            filtered_registry = type(registry).__new__(type(registry))
            filtered_registry._tools = {}
            filtered_registry._feature_flags = {}
            for name in allowed:
                if registry.has(name):
                    filtered_registry._tools[name] = registry.get(name)
                    filtered_registry._feature_flags.setdefault("auto", set()).add(name)

            # 获取 API 配置
            from mai_agent.config import get_config
            cfg = get_config()
            llm = LLMClient(
                api_key=cfg.llm_api_key,
                base_url=cfg.llm_base_url or "https://api.deepseek.com/v1",
                model=cfg.llm_model,
            )

            answer, _ = await agent_loop(
                user_input=prompt,
                llm=llm,
                registry=filtered_registry,
                context=sub_context,
                config=sub_config,
            )

            return {
                "index": idx,
                "prompt": prompt[:100],
                "ok": True,
                "output": answer[:1000] if answer else "",
            }

        except Exception as exc:
            return {
                "index": idx,
                "prompt": prompt[:100],
                "ok": False,
                "error": str(exc),
            }


registry.register(WorkflowTool())
