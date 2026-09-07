"""生成文档与 Skill 路由完整性回归。

防止两类"文档与代码脱钩"再次发生：
  1. generated-module-map.md 过期（模块增删后忘了重跑 extract_module_map.py）；
  2. repo-map/core-loop 路由表指向的领域 Skill 缺失（mai-tools/mai-hooks/...）。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / ".mai" / "skills" / "mai-repo-map" / "references" / "generated-module-map.md"
ROUTED_SKILLS = [
    "mai-tools", "mai-hooks", "mai-llm",
    "mai-services", "mai-knowledge", "mai-mcp",
    "mai-core-loop", "mai-repo-map",
]


class TestModuleMapFreshness:
    def test_map_covers_new_modules(self):
        text = MAP.read_text(encoding="utf-8")
        assert "cron_scheduler" in text, "新模块 cron_scheduler 未进模块地图（重跑 extract_module_map.py）"
        assert "services/cron_scheduler.py" in text
        assert "feishu" in text

    def test_map_no_dead_modules(self):
        text = MAP.read_text(encoding="utf-8")
        assert "coordinator" not in text, "已删除的 coordinator 仍残留在模块地图（重跑 extract_module_map.py）"

    def test_map_header_is_generated(self):
        first = MAP.read_text(encoding="utf-8").splitlines()[0]
        assert "Generated Module Map" in first


class TestSkillRoutingClosed:
    def test_all_routed_skills_exist(self):
        missing = [s for s in ROUTED_SKILLS
                   if not (ROOT / ".mai" / "skills" / s / "SKILL.md").exists()]
        assert not missing, f"路由表指向的 Skill 缺失: {missing}"

    def test_skill_frontmatter_valid(self):
        for s in ROUTED_SKILLS:
            head = (ROOT / ".mai" / "skills" / s / "SKILL.md").read_text(
                encoding="utf-8").split("---")[1]
            for key in ("name", "description", "whenToUse"):
                assert f"{key}:" in head, f"{s} 缺 frontmatter 字段 {key}"
