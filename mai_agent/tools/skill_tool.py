"""Skill 工具 — 对应 Claude Code 的 SkillTool。

模型通过查看 system prompt 中的 "可用 skill 列表" 决定何时调用，
调用本工具按名激活 skill，skill 的完整指令被返回给模型作为 tool_result，
模型据此在当前回合遵循该 skill 的指令。

对应 Claude Code 的 Skill 调用流程：
  1. system prompt 注入 available-skills 一行描述列表
  2. 模型判断需要某 skill → 调用 Skill 工具
  3. 工具读取 SKILL.md 正文 → 作为 tool_result 返回
  4. 模型读到正文后在后续行动中遵循该 skill
"""

from __future__ import annotations

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry


class SkillInput(ToolInput):
    skill: str = Field(description="要激活的 skill 名称（来自可用 skill 列表）")
    args: str = Field(default="", description="可选: 传递给 skill 的参数")


class SkillTool(Tool):
    """激活一个已加载的 skill，将其指令注入当前回合上下文。

    Claude Code 对应物: SkillTool + skills/ 加载机制。
    """
    name = "Skill"
    description = (
        "激活一个预设 skill。skill 是打包好的指令集，调用后其完整指令会返回给你，"
        "你应在后续行动中遵循。仅使用 system prompt 中列出的可用 skill 名称。"
    )
    input_schema = SkillInput
    is_concurrency_safe = True  # 只读 skill 文件，无副作用

    async def call(self, input: SkillInput, context: RunContext) -> str:
        from mai_agent.skills.loader import get_skill_registry

        project_root = context.session_state.get("project_root", context.cwd)
        reg = get_skill_registry(project_root)

        skill = reg.get(input.skill)
        if skill is None:
            available = ", ".join(s.name for s in reg.all()) or "(无)"
            return (
                f"[ERROR] 未知 skill: {input.skill}。"
                f"可用: {available}"
            )

        parts = [
            f"[Skill 激活: {skill.name}]",
            f"描述: {skill.description}",
        ]
        if skill.when_to_use:
            parts.append(f"触发场景: {skill.when_to_use}")
        if input.args:
            parts.append(f"传入参数: {input.args}")
        parts.append("")
        parts.append("— skill 指令正文 —")
        parts.append(skill.content if skill.content else "(skill 无正文指令)")
        parts.append("— 指令正文结束 —")
        parts.append("")
        parts.append("请在后续行动中遵循上述指令完成当前任务。")

        return "\n".join(parts)


registry.register(SkillTool())
