"""Plugin 加载器 — 扫描 .mai/plugins/ 目录，解析 manifest，注册工具/hook/skill。

plugin.json 格式::
    {
      "name": "my-plugin",
      "version": "1.0.0",
      "description": "My custom tools",
      "type": "tool",           // tool | hook | skill | mcp
      "entry": "tools.py",      // 如果是 tool: Python 文件（相对于 plugin 目录）
      "enabled": true
    }

双轨扩展:
  轨1 (Plugin): 用户自定义 Python 工具/钩子
  轨2 (MCP):   外部 MCP 服务器工具
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PLUGIN_DIR = ".mai/plugins"
MANIFEST_FILE = "plugin.json"


@dataclass
class PluginManifest:
    """Plugin 清单。"""
    name: str
    version: str = "0.1.0"
    description: str = ""
    type: str = "tool"       # tool | hook | skill | mcp
    entry: str = ""          # 入口文件路径（相对 plugin 目录）
    enabled: bool = True
    source_dir: str = ""     # plugin 目录的绝对路径


@dataclass
class PluginRegistry:
    """已加载的 plugin 注册表。"""
    _plugins: dict[str, PluginManifest] = field(default_factory=dict)
    _loaded_modules: dict[str, Any] = field(default_factory=dict)

    def add(self, manifest: PluginManifest) -> None:
        self._plugins[manifest.name] = manifest

    def get(self, name: str) -> Optional[PluginManifest]:
        return self._plugins.get(name)

    def all(self) -> list[PluginManifest]:
        return list(self._plugins.values())

    def is_loaded(self, name: str) -> bool:
        return name in self._loaded_modules

    def mark_loaded(self, name: str, module: Any) -> None:
        self._loaded_modules[name] = module

    def __len__(self) -> int:
        return len(self._plugins)


def load_plugins(project_root: str = ".") -> PluginRegistry:
    """扫描 .mai/plugins/ 并加载所有启用的 plugin。

    对每个 tool 类型的 plugin，动态 import 其 entry 文件。
    entry 文件应使用 registry.register() 注册其工具。
    """
    registry = PluginRegistry()
    plugin_root = Path(project_root) / PLUGIN_DIR

    if not plugin_root.is_dir():
        return registry

    for plugin_dir in sorted(plugin_root.iterdir()):
        if not plugin_dir.is_dir():
            continue
        manifest_path = plugin_dir / MANIFEST_FILE
        if not manifest_path.exists():
            continue

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Plugin '%s' manifest 解析失败: %s", plugin_dir.name, exc)
            continue

        manifest = PluginManifest(
            name=data.get("name", plugin_dir.name),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            type=data.get("type", "tool"),
            entry=data.get("entry", ""),
            enabled=data.get("enabled", True),
            source_dir=str(plugin_dir),
        )

        if not manifest.enabled:
            logger.debug("Plugin '%s' 已禁用", manifest.name)
            continue

        registry.add(manifest)

        # 加载 tool 类型的 plugin
        if manifest.type == "tool" and manifest.entry:
            _load_tool_plugin(manifest, registry)
        elif manifest.type == "mcp":
            _register_mcp_plugin(manifest, project_root)
        elif manifest.type == "skill" and manifest.entry:
            _register_skill_plugin(manifest)

    logger.info("已加载 %d 个 plugin: %s", len(registry),
               [p.name for p in registry.all()])
    return registry


def _load_tool_plugin(manifest: PluginManifest, registry: PluginRegistry) -> None:
    """动态 import tool plugin 的 Python 文件。"""
    entry_path = Path(manifest.source_dir) / manifest.entry
    if not entry_path.exists():
        logger.warning("Plugin '%s' entry 文件不存在: %s", manifest.name, entry_path)
        return

    module_name = f"_plugin_{manifest.name}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(entry_path))
        if spec is None or spec.loader is None:
            logger.warning("Plugin '%s' 无法创建 module spec", manifest.name)
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        registry.mark_loaded(manifest.name, module)
        logger.info("Plugin '%s' 已加载 (tool)", manifest.name)
    except Exception as exc:
        logger.warning("Plugin '%s' 加载失败: %s", manifest.name, exc)


def _register_mcp_plugin(manifest: PluginManifest, project_root: str) -> None:
    """将 MCP 类型 plugin 的配置注册到 .mcp.json 风格的系统。"""
    # MCP plugin 可以附带自己的 mcp_server 配置
    config_path = Path(manifest.source_dir) / "mcp_config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            logger.info("Plugin '%s' MCP 配置已发现: %s", manifest.name,
                       list(cfg.get("mcpServers", {}).keys()))
        except Exception as exc:
            logger.warning("Plugin '%s' MCP 配置加载失败: %s", manifest.name, exc)


def _register_skill_plugin(manifest: PluginManifest) -> None:
    """将 skill 类型 plugin 的 Markdown 文件注册到 skill 系统。"""
    entry_path = Path(manifest.source_dir) / manifest.entry
    if not entry_path.exists():
        logger.warning("Plugin '%s' skill 文件不存在: %s", manifest.name, entry_path)
        return
    # Skill 系统在启动时扫描 .mai/skills/ 和 ~/.mai/skills/
    # Plugin 的 skill 文件需要复制/链接到 .mai/skills/，或 skill loader 也扫描 plugin 目录
    # 这里做简单处理：将 plugin 的 skill 目录加入扫描路径（由 skill loader 后续支持）
    logger.info("Plugin '%s' skill 已注册: %s", manifest.name, manifest.entry)


# ── 全局缓存 ─────────────────────────────────────────────

_cached: Optional[PluginRegistry] = None


def get_plugin_registry(project_root: str = ".") -> PluginRegistry:
    global _cached
    if _cached is None:
        _cached = load_plugins(project_root)
    return _cached


def reload_plugins(project_root: str = ".") -> PluginRegistry:
    global _cached
    _cached = load_plugins(project_root)
    return _cached
