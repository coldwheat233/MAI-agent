"""AskUserQuestion — 对应 Claude Code 的 AskUserQuestionTool。

模型遇到模糊需求时，调用此工具向用户提问，而不是猜测意图。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry


class Question(BaseModel):
    question: str = Field(description="问题内容")
    header: str = Field(description="简短标签，最多12字符")
    options: list[dict[str, str]] = Field(
        default_factory=list,
        description="可选: [{label, description}]。空列表允许自由输入。"
    )


class AskUserQuestionInput(ToolInput):
    questions: list[dict[str, Any]] = Field(
        description="要问的问题列表。每个问题: {question, header, options?}"
    )


class AskUserQuestionTool(Tool):
    """模型调用此工具向用户提问。

    Claude Code 对应物: AskUserQuestionTool。

    触发时机:
      - 需求模糊（"帮我加个功能" → 什么功能？）
      - 多个可行方案（"你想用 A 还是 B？"）
      - 需要确认（"这个操作会删除文件，确认吗？"）
    """
    name = "AskUserQuestion"
    description = "向用户提问以澄清模糊需求、选择方案或确认操作。当你不确定时使用，不要猜测。"
    input_schema = AskUserQuestionInput
    is_concurrency_safe = False  # 需要用户交互

    async def call(self, input: AskUserQuestionInput, context: RunContext) -> str:
        questions = input.questions
        if not questions:
            return "[ERROR] questions cannot be empty"

        # In non-interactive mode, just return the questions as text
        if context.permission_mode == "auto":
            lines = ["[Questions from model:]"]
            for q in questions:
                lines.append(f"\n### {q.get('header', '?')}")
                lines.append(q.get('question', ''))
                opts = q.get('options', [])
                if opts:
                    for o in opts:
                        label = o.get('label', '?')
                        desc = o.get('description', '')
                        lines.append(f"  - {label}: {desc}")
            return "\n".join(lines)

        # Interactive mode: show questions to user and collect answers
        answers: dict[str, str] = {}
        for q in questions:
            header = q.get('header', '?')
            question = q.get('question', '')
            opts = q.get('options', [])

            print(f"\n{'='*60}")
            print(f"[{header}] {question}")
            if opts:
                for i, o in enumerate(opts, 1):
                    label = o.get('label', '')
                    desc = o.get('description', '')
                    print(f"  {i}. {label} — {desc}")
                choice = input(f"Choose (1-{len(opts)}): ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(opts):
                    answers[header] = opts[int(choice) - 1]['label']
                else:
                    answers[header] = choice
            else:
                answer = input("Answer: ").strip()
                answers[header] = answer or "(no answer)"

        # Format answers for model
        result = ["[User answers:]"]
        for k, v in answers.items():
            result.append(f"- {k}: {v}")
        return "\n".join(result)


registry.register(AskUserQuestionTool())
