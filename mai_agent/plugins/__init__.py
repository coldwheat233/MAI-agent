"""Plugin 双轨扩展系统 — 对应 Claude Code 的 plugins/ 目录。

Plugin 类型:
  - tool: 注册新工具到 ToolRegistry
  - hook: 注册 PreToolUse/PostToolUse hook
  - skill: 注册新 skill（Markdown 指令集）
  - mcp: 注册 MCP 服务器配置

Plugin 清单: .mai/plugins/<name>/plugin.json
"""

from mai_agent.plugins.loader import (
    PluginManifest,
    PluginRegistry,
    load_plugins,
    get_plugin_registry,
)

__all__ = ["PluginManifest", "PluginRegistry", "load_plugins", "get_plugin_registry"]
