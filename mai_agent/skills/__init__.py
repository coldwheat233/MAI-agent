"""Skill 系统 — 对应 Claude Code 的 skills/ 目录。

Skill 是打包好的、用户/插件预设的指令集。模型通过查看 system prompt 中的
"可用 skill 列表"（一行描述）来判断何时调用，然后调用 Skill 工具按名激活，
该 skill 的完整指令被注入到当前回合的上下文中。

Skill 文件格式（Markdown + YAML frontmatter）::

    ---
    name: my-skill
    description: 一句话描述这个 skill 做什么
    whenToUse: 在什么场景下使用
    ---

    # My Skill

    具体指令正文...
"""
from mai_agent.skills.loader import (
    Skill,
    SkillRegistry,
    load_skills,
    get_skill_registry,
)

__all__ = ["Skill", "SkillRegistry", "load_skills", "get_skill_registry"]
