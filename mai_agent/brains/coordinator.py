"""Coordinator — 四脑调度状态机。

Modeled after the book's "Proposer-Checker" pattern + Claude Code's coordinator.

States:
    IDLE       → waiting for user input
    EXPLORING  → dev_explorer generates checklist
    VALIDATING → dev_validator verifies each item
    COMPLETED  → all items CLOSED, ready for deploy (future)
    BLOCKED    → validator found OPEN items, needs replan

Transitions:
    IDLE → EXPLORING     user submits task
    EXPLORING → VALIDATING    checklist artifact written
    VALIDATING → COMPLETED    all items CLOSED
    VALIDATING → EXPLORING    items remain OPEN (loop back)
    COMPLETED → IDLE          done
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from mai_agent.brains.definitions import (
    DEV_EXPLORER,
    DEV_VALIDATOR,
    ALL_BRAINS,
)
from mai_agent.core.models import SystemMessage, UserMessage, Message
from mai_agent.llm.client import LLMClient
from mai_agent.tools.base import RunContext
from mai_agent.tools.registry import ToolRegistry
from mai_agent.tools.orchestration import (
    ToolUseBlock,
    run_tools,
    ToolExecutionResult,
)

logger = logging.getLogger(__name__)


# ── State Machine ────────────────────────────────────────


class BrainState(str, Enum):
    IDLE = "idle"
    EXPLORING = "exploring"
    VALIDATING = "validating"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class CoordinatorContext:
    """Mutable state tracked across the brain lifecycle."""
    state: BrainState = BrainState.IDLE
    checklist_path: Optional[str] = None
    iteration: int = 0
    max_iterations: int = 3  # prevent infinite loop
    open_items: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)  # state transition log

    def status_bar(self) -> str:
        """Generate a structured status summary for injection into LLM context.

        This is the "Agent状态栏" pattern from the book:
        A condensed status block that the model can glance at before each turn.
        """
        lines = [
            f"[Agent Status] state={self.state.value} cycle={self.iteration}/{self.max_iterations}",
        ]
        if self.checklist_path:
            lines.append(f"checklist={self.checklist_path}")
        if self.open_items:
            items = "; ".join(self.open_items[:5])
            lines.append(f"open_items={items}")
        if self.history:
            lines.append(f"last_transitions={', '.join(self.history[-3:])}")
        return "\n".join(lines)


# ── Sub-brain runner ─────────────────────────────────────


async def _run_brain(
    brain_name: str,
    task_prompt: str,
    status_bar: str,
    registry: ToolRegistry,
    context: RunContext,
    model: str = "deepseek-v4-pro",
    api_key: str = "",
    base_url: str = "https://api.deepseek.com/v1",
    max_turns: int = 12,
) -> str:
    """Run a single brain as an isolated sub-agent.

    Returns the brain's final text output.
    """
    definition = ALL_BRAINS.get(brain_name)
    if not definition:
        return f"[ERROR] Unknown brain: {brain_name}"

    llm = LLMClient(api_key=api_key, base_url=base_url, model=model)

    # Inject status bar into system prompt so the brain knows where we are
    full_prompt = f"{definition.prompt}\n\n{status_bar}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": full_prompt},
        {"role": "user", "content": task_prompt},
    ]

    # Filter tools to the brain's allowlist
    tools = [
        t for t in registry.to_openai_schemas("auto")
        if t["function"]["name"] in set(definition.allowed_tools)
    ]

    for step in range(1, max_turns + 1):
        response = await llm.chat(messages, tools=tools)

        # Append assistant
        msg: dict[str, Any] = {"role": "assistant"}
        if response.content:
            msg["content"] = response.content
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name if tc.function else "",
                        "arguments": tc.function.arguments if tc.function else "{}",
                    },
                }
                for tc in response.tool_calls
            ]
        messages.append(msg)

        if not response.tool_calls:
            return response.content or "(empty)"

        # Execute tools
        blocks = [
            ToolUseBlock(
                id=tc.id,
                name=tc.function.name if tc.function else "",
                input=_safe_json(tc.function.arguments if tc.function else "{}"),
            )
            for tc in response.tool_calls
        ]

        async for result in run_tools(blocks, registry, context):
            messages.append({
                "role": "tool",
                "tool_call_id": result.message.tool_use_id,
                "content": result.message.content,
            })

    return "(max turns reached)"


# ── Verdict Parser ────────────────────────────────────────


def parse_verdict(output: str) -> tuple[BrainState, list[str]]:
    """Parse a brain's output to determine the verdict.

    Looks for CLOSED/OPEN markers in the text.
    Returns (next_state, open_items).
    """
    text = output.lower()

    # Check for CLOSED signal
    if re.search(r"闭合状态.*closed|logical.*closed|all.*passed|全部.*通过|闭合.*是", text, re.IGNORECASE):
        return BrainState.COMPLETED, []

    # Extract OPEN items if present
    open_items: list[str] = []
    # Try to find a structured open-items section
    open_section = re.search(
        r"(?:open_items|未完成|遗留|open|blocked)[:：]\s*(.+?)(?:\n\n|$)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if open_section:
        items = re.findall(r"[-*]\s*(.+)", open_section.group(1))
        open_items = [i.strip() for i in items if i.strip()]

    if open_items:
        return BrainState.BLOCKED, open_items

    # If we see "not all passed" or similar signals
    if re.search(r"not.*(?:pass|close)|fail|blocked|open|未完成|不通过", text, re.IGNORECASE):
        return BrainState.BLOCKED, ["(parsed from verdict — see validator output for details)"]

    # Default: assume completed if no blockers found
    return BrainState.COMPLETED, []


# ── The Coordinator ───────────────────────────────────────


class Coordinator:
    """Orchestrates the four-brain lifecycle.

    Usage::

        coord = Coordinator(registry, context)
        coord.start()

        # 先 triage——让 LLM 自己判断当前消息是否需要探索
        if await coord.should_run(user_input):
            result = await coord.run_full_cycle(user_input)
    """

    def __init__(
        self,
        registry: ToolRegistry,
        context: RunContext,
        model: str = "deepseek-v4-pro",
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
    ):
        self.registry = registry
        self.context = context
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.state = CoordinatorContext()

    def start(self) -> None:
        self.state = CoordinatorContext()

    async def should_run(self, user_input: str) -> bool:
        """LLM 驱动的 triage——让模型判断这条消息是否需要结构化探索。

        判断依据:
        - 是否为开发/分析任务（vs 闲聊、纯提问）
        - 是否需要拆解成多步骤
        - 是否已有活跃的 checklist（是→可能只需要验证）

        用一个极短的 LLM 调用（max_tokens=5）做二分判断。
        """
        # 上一轮已经完成且没有新 checklist 的短消息直接跳过
        has_active_checklist = (
            self.state.checklist_path is not None
            and self.state.state != BrainState.IDLE
        )

        triage_prompt = (
            "Classify this user message. Answer YES or NO.\n\n"
            "Answer YES if the message requires structured task analysis "
            "(checklist generation / validation / multi-step planning).\n"
            "Answer NO if it is a conversational question, a simple one-shot reply, "
            "greeting, or follow-up clarification.\n\n"
            f"Message: {user_input[:500]}\n\n"
        )
        if has_active_checklist:
            triage_prompt += (
                f"Context: An active checklist exists ({self.state.checklist_path}). "
                f"State: {self.state.state.value}. "
                "If this message is continuing that work, answer YES.\n\n"
            )
        triage_prompt += "Answer (YES/NO):"

        try:
            llm = LLMClient(
                api_key=self.api_key, base_url=self.base_url, model=self.model,
            )
            resp = await llm.chat(
                messages=[{"role": "user", "content": triage_prompt}],
                temperature=0.0, max_tokens=5,
            )
            answer = (resp.content or "").strip().upper()
            decision = answer.startswith("YES")
            logger.info(
                "Coordinator triage: '%s' → decision=%s (has_checklist=%s, state=%s)",
                (user_input)[:60], decision, has_active_checklist, self.state.state.value,
            )
            return decision
        except Exception as exc:
            logger.warning("Coordinator triage LLM 调用失败，默认 YES: %s", exc)
            return True  # 宁可多跑，不要漏

    def _status(self) -> str:
        return self.state.status_bar()

    async def explore(self, user_task: str) -> str:
        """Phase 1: Run dev_explorer to generate a checklist artifact.

        Returns the path to the generated checklist file.
        """
        self.state.state = BrainState.EXPLORING
        self.state.iteration += 1
        self.state.history.append("→ EXPLORING")

        prompt = (
            f"用户任务: {user_task}\n\n"
            f"请分析此任务，读取相关文件了解项目现状，然后生成一个可执行的开发 checklist。\n"
            f"将 checklist 写入文件 `.mai/checklist_{self.state.iteration:03d}.md`。\n"
            f"输出格式: 每个检查项以 `- [ ]` 开头，包含具体的验收条件。"
        )

        output = await _run_brain(
            "dev_explorer", prompt, self._status(),
            self.registry, self.context, self.model,
            api_key=self.api_key, base_url=self.base_url,
        )

        # Determine checklist path
        checklist_path = f".mai/checklist_{self.state.iteration:03d}.md"
        self.state.checklist_path = checklist_path

        logger.info("Explorer completed. checklist=%s", checklist_path)
        self.state.history.append(f"explored → {checklist_path}")
        return checklist_path

    async def validate(self, checklist_path: Optional[str] = None) -> tuple[BrainState, list[str]]:
        """Phase 2: Run dev_validator to verify the checklist.

        Returns (next_state, open_items).
        """
        self.state.state = BrainState.VALIDATING
        self.state.history.append("→ VALIDATING")

        path = checklist_path or self.state.checklist_path or ".mai/checklist_001.md"

        prompt = (
            f"请验证以下 checklist 中的所有项目: `{path}`\n\n"
            f"对每一项:\n"
            f"1. 检查代码是否已实现\n"
            f"2. 如果需要，运行测试验证\n"
            f"3. 标记该项为 DONE 或 OPEN\n\n"
            f"最后给出总体结论:\n"
            f"- 闭合状态: CLOSED (全部完成) 或 OPEN (有遗留项)\n"
            f"- 如果 OPEN，列出所有未完成的项"
        )

        output = await _run_brain(
            "dev_validator", prompt, self._status(),
            self.registry, self.context, self.model,
            api_key=self.api_key, base_url=self.base_url,
        )

        next_state, open_items = parse_verdict(output)
        self.state.open_items = open_items

        if next_state == BrainState.COMPLETED:
            self.state.state = BrainState.COMPLETED
            self.state.history.append("→ COMPLETED")
            logger.info("Validator: CLOSED. All checks passed.")
        else:
            self.state.state = BrainState.BLOCKED
            self.state.history.append(f"→ BLOCKED ({len(open_items)} items)")
            logger.info("Validator: BLOCKED. Open items: %s", open_items)

        return next_state, open_items

    async def run_full_cycle(self, user_task: str) -> str:
        """Run a complete explore→validate cycle, with loop-back on BLOCKED.

        Returns a summary message suitable for the user.

        状态由调用方预先设入 self.state（含跨轮迭代计数），
        本方法只推进——不重置。"""
        checklist = await self.explore(user_task)

        while self.state.iteration < self.state.max_iterations:
            next_state, open_items = await self.validate(checklist)

            if next_state == BrainState.COMPLETED:
                return (
                    f"[PASS] All checks passed.\n"
                    f"Checklist: {checklist}\n"
                    f"Cycles: {self.state.iteration}"
                )

            # BLOCKED — loop back
            feedback = "以下项目未完成:\n" + "\n".join(f"- {i}" for i in open_items)
            logger.info("Looping back to explorer. Feedback: %s", feedback)

            checklist = await self.explore(
                f"{user_task}\n\n(上次验证反馈)\n{feedback}\n请针对遗留项重新规划。"
            )

        return (
            f"[WARN] Max iterations ({self.state.max_iterations}) reached.\n"
            f"遗留项: {self.state.open_items}\n"
            f"请人工检查 {self.state.checklist_path}"
        )


# ── Helpers ───────────────────────────────────────────────


def _safe_json(s: str) -> dict[str, Any]:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}
