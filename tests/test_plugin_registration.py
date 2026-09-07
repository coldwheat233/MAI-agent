"""P1-4 回归：Plugin 双轨（skill / mcp）真正注册。

旧缺口：
  - type=skill 的 plugin 只打日志（"由 skill loader 后续支持"空转）；
  - type=mcp 的 plugin 只发现 mcp_config.json 不并入启动集合。
现在：skill → register_extra_skill_dir 进扫描路径；mcp → 并入
get_plugin_mcp_servers()，被 load_mcp_config 与 .mcp.json 合并启动。
"""

from __future__ import annotations

import json
from pathlib import Path

from mai_agent.plugins import loader as plugins_loader
from mai_agent.skills import loader as skills_loader
from mai_agent.tools import mcp_tools


def _plugin_dir(root: Path, name: str, ptype: str, entry: str = "") -> Path:
    d = root / ".mai" / "plugins" / name
    d.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": "0.1.0", "description": "t", "type": ptype}
    if entry:
        manifest["entry"] = entry
    (d / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def _reset_state(monkeypatch):
    """清掉跨测试的模块级状态（缓存/注册集合）。"""
    monkeypatch.setattr(plugins_loader, "_plugin_mcp_servers", {})
    monkeypatch.setattr(skills_loader, "_extra_skill_dirs", {})
    monkeypatch.setattr(skills_loader, "_cached_registry", None)
    monkeypatch.setattr(skills_loader, "_cached_root", "")


SKILL_MD = """---
name: {name}
description: {desc}
whenToUse: {when}
---
# {name}

正文。
"""


class TestSkillTrack:
    def test_dir_of_skills_loaded(self, tmp_path, monkeypatch):
        _reset_state(monkeypatch)
        p = _plugin_dir(tmp_path, "plug-a", "skill", "skills")
        sdir = p / "skills" / "my-checker"
        sdir.mkdir(parents=True)
        (sdir / "SKILL.md").write_text(
            SKILL_MD.format(name="my-checker", desc="校验代码", when="需要验证时"),
            encoding="utf-8",
        )

        plugins_loader.load_plugins(str(tmp_path))
        reg = skills_loader.load_skills(str(tmp_path))
        assert reg.get("my-checker") is not None
        skill = reg.get("my-checker")
        assert skill.description == "校验代码"
        assert "正文" in skill.content
        assert "my-checker" in reg.listing()

    def test_single_skill_dir_entry(self, tmp_path, monkeypatch):
        _reset_state(monkeypatch)
        p = _plugin_dir(tmp_path, "plug-solo", "skill", "linter")
        solo = p / "linter"
        solo.mkdir()
        (solo / "SKILL.md").write_text(
            SKILL_MD.format(name="lint", desc="lint 代码", when="改代码后"),
            encoding="utf-8",
        )
        plugins_loader.load_plugins(str(tmp_path))
        reg = skills_loader.load_skills(str(tmp_path))
        assert reg.get("lint") is not None

    def test_missing_dir_warns_not_crash(self, tmp_path, monkeypatch):
        _reset_state(monkeypatch)
        _plugin_dir(tmp_path, "plug-bad", "skill", "nonexistent")
        # 不应抛异常
        plugins_loader.load_plugins(str(tmp_path))
        assert True


class TestMcpTrack:
    def test_plugin_mcp_merged_into_load_mcp_config(self, tmp_path, monkeypatch):
        _reset_state(monkeypatch)
        p = _plugin_dir(tmp_path, "plug-mcp", "mcp")
        (p / "mcp_config.json").write_text(json.dumps({
            "mcpServers": {
                "pluginA": {"command": "uvx", "args": ["srv-a"], "enabled": True},
                "pluginOff": {"command": "npx", "args": ["srv-b"], "enabled": False},
            },
        }), encoding="utf-8")

        plugins_loader.load_plugins(str(tmp_path))
        servers = plugins_loader.get_plugin_mcp_servers()
        assert "pluginA" in servers
        assert "pluginOff" not in servers, "enabled=false 的 server 不注册"

        # .mcp.json 与 plugin 服务器合并
        (tmp_path / ".mcp.json").write_text(json.dumps({
            "mcpServers": {"dotjsonSrv": {"command": "npx", "args": ["x"], "enabled": True}},
        }), encoding="utf-8")
        configs = mcp_tools.load_mcp_config(str(tmp_path))
        names = {c.name for c in configs}
        assert names == {"dotjsonSrv", "pluginA"}
        # 校验 enabled 透传
        by_name = {c.name: c for c in configs}
        assert by_name["pluginA"].enabled is True

    def test_dotjson_same_name_wins(self, tmp_path, monkeypatch):
        _reset_state(monkeypatch)
        p = _plugin_dir(tmp_path, "plug-mcp2", "mcp")
        (p / "mcp_config.json").write_text(json.dumps({
            "mcpServers": {"dup": {"command": "plugin-cmd", "args": []}},
        }), encoding="utf-8")
        (tmp_path / ".mcp.json").write_text(json.dumps({
            "mcpServers": {"dup": {"command": "dotjson-cmd", "args": []}},
        }), encoding="utf-8")
        plugins_loader.load_plugins(str(tmp_path))
        configs = mcp_tools.load_mcp_config(str(tmp_path))
        cfg = next(c for c in configs if c.name == "dup")
        assert cfg.command == "dotjson-cmd", ".mcp.json 同名优先"
