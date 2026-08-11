"""Tests for the Skill system — loader, frontmatter parsing, SkillTool."""

import pytest

from mai_agent.skills.loader import (
    Skill,
    SkillRegistry,
    load_skills,
    _parse_frontmatter,
)


def test_parse_frontmatter_basic():
    text = """---
name: my-skill
description: Does a thing
whenToUse: when you need a thing done
---

# My Skill

Do the thing.
"""
    meta, body = _parse_frontmatter(text)
    assert meta["name"] == "my-skill"
    assert meta["description"] == "Does a thing"
    assert meta["whenToUse"] == "when you need a thing done"
    assert "Do the thing" in body


def test_parse_frontmatter_no_frontmatter():
    text = "Just plain markdown, no frontmatter."
    meta, body = _parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_skill_listing_line():
    s = Skill(name="deploy", description="Deploys the app", when_to_use="after tests pass")
    line = s.listing_line()
    assert "deploy" in line
    assert "Deploys the app" in line
    assert "after tests pass" in line


def test_skill_registry_listing_empty():
    reg = SkillRegistry()
    assert reg.listing() == ""


def test_skill_registry_listing():
    reg = SkillRegistry()
    reg.add(Skill(name="a", description="alpha"))
    reg.add(Skill(name="b", description="beta"))
    listing = reg.listing()
    assert "a" in listing
    assert "b" in listing
    assert listing.index("a") < listing.index("b")  # sorted


def test_load_skills_from_dir(temp_dir):
    skill_dir = f"{temp_dir}/.mai/skills"
    import os
    os.makedirs(skill_dir)
    with open(f"{skill_dir}/deploy.md", "w", encoding="utf-8") as f:
        f.write("""---
name: deploy
description: Deploys the app
whenToUse: after tests pass
---

# Deploy

Run the deploy script.
""")
    reg = load_skills(temp_dir)
    assert len(reg) == 1
    skill = reg.get("deploy")
    assert skill is not None
    assert skill.description == "Deploys the app"
    assert "Run the deploy script" in skill.content
    assert skill.source == "project"


@pytest.mark.asyncio
async def test_skill_tool_activates(temp_dir):
    from mai_agent.tools.skill_tool import SkillTool
    from mai_agent.tools.base import RunContext

    # Create a skill
    import os
    skill_dir = f"{temp_dir}/.mai/skills"
    os.makedirs(skill_dir)
    with open(f"{skill_dir}/lint.md", "w", encoding="utf-8") as f:
        f.write("""---
name: lint
description: Lint the codebase
whenToUse: before commit
---

Run ruff and fix issues.
""")

    ctx = RunContext(cwd=temp_dir, session_state={"project_root": temp_dir})
    tool = SkillTool()
    result = await tool.execute({"skill": "lint"}, ctx)
    assert not result.is_error
    assert "Run ruff and fix issues" in result.content
    assert "lint" in result.content


@pytest.mark.asyncio
async def test_skill_tool_unknown(temp_dir):
    from mai_agent.tools.skill_tool import SkillTool
    from mai_agent.tools.base import RunContext

    ctx = RunContext(cwd=temp_dir, session_state={"project_root": temp_dir})
    tool = SkillTool()
    result = await tool.execute({"skill": "nonexistent"}, ctx)
    assert result.is_error
    assert "未知 skill" in result.content
