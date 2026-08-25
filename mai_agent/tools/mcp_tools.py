"""MCP 工具适配器 — 将外部 MCP 服务器的工具注册到 MAI-agent 工具系统。

每个 MCP 服务器的每个工具生成一个 MCPToolWrapper 实例，
统一通过 ToolRegistry 暴露给 LLM。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry
from mai_agent.services.mcp_client import MCPClient, MCPServerConfig, MCPToolDef

logger = logging.getLogger(__name__)

# 全局 MCP 客户端管理
_mcp_clients: dict[str, MCPClient] = {}


class MCPToolInput(ToolInput):
    """MCP 工具的通用输入 schema。参数由 MCP 服务器的 inputSchema 动态定义。"""
    # 基础 MCP 参数
    mcp_arguments: str = Field(
        default="{}",
        description="JSON-encoded arguments for the MCP tool. e.g. '{\"path\": \"/tmp/x.txt\"}'"
    )


class MCPToolWrapper(Tool):
    """MCP 工具包装器 — 把一个 MCP 工具暴露为 MAI-agent Tool。

    每个 MCP 工具生成一个实例，注册到全局 ToolRegistry。
    """

    def __init__(self, tool_def: MCPToolDef, client: MCPClient):
        self._tool_def = tool_def
        self._client = client
        self.name = f"mcp__{tool_def.server_name}__{tool_def.name}"
        self.description = f"[MCP:{tool_def.server_name}] {tool_def.description}"
        self.input_schema = MCPToolInput
        self.is_concurrency_safe = False  # MCP 工具默认串行（保守）

    async def call(self, input: MCPToolInput, context: RunContext) -> str:
        import json as _json
        try:
            args = _json.loads(input.mcp_arguments)
        except _json.JSONDecodeError:
            return f"[ERROR] 无效的 JSON 参数: {input.mcp_arguments}"

        try:
            result = await self._client.call_tool(self._tool_def.name, args)
            return result
        except Exception as exc:
            return f"[ERROR] MCP 工具 '{self._tool_def.name}' 执行失败: {exc}"


# ── MCP 服务管理器 ───────────────────────────────────────


async def start_mcp_servers(configs: list[MCPServerConfig]) -> list[MCPToolWrapper]:
    """启动所有 MCP 服务器并注册其工具。

    Args:
        configs: MCP 服务器配置列表

    Returns:
        已注册的 MCP 工具包装器列表
    """
    wrappers: list[MCPToolWrapper] = []
    for cfg in configs:
        if not cfg.enabled:
            continue
        # 幂等：同一进程内该服务器已启动则跳过（engine.start fire-and-forget 与 cli await 双路径可能重复）
        if cfg.name in _mcp_clients:
            logger.info("MCP '%s' 已在运行，跳过", cfg.name)
            continue
        try:
            client = MCPClient(cfg)
            await client.start()
            tools = await client.list_tools()
            _mcp_clients[cfg.name] = client

            for td in tools:
                wrapper = MCPToolWrapper(td, client)
                try:
                    registry.register(wrapper)
                except ValueError:
                    # 工具已注册（重复注册保护），跳过但不失败
                    logger.debug("MCP 工具已存在，跳过: %s", wrapper.name)
                    continue
                wrappers.append(wrapper)
                logger.info("MCP 工具已注册: %s (%s)", wrapper.name, td.description)

            logger.info("MCP '%s': %d 个工具已加载", cfg.name, len(tools))
        except Exception as exc:
            logger.warning("MCP '%s' 启动失败: %s", cfg.name, exc)

    return wrappers


async def stop_all_mcp() -> None:
    """停止所有 MCP 服务器并取消注册工具。"""
    for name, client in list(_mcp_clients.items()):
        try:
            await client.stop()
        except Exception as exc:
            logger.warning("MCP '%s' 停止失败: %s", name, exc)
    _mcp_clients.clear()

    # 清除 MCP 工具注册
    to_remove = [n for n in registry.names() if n.startswith("mcp__")]
    for name in to_remove:
        try:
            del registry._tools[name]
        except KeyError:
            pass


def load_mcp_config(project_root: str = ".") -> list[MCPServerConfig]:
    """从 .mcp.json 加载 MCP 服务器配置。

    .mcp.json 格式::

        {
          "mcpServers": {
            "filesystem": {
              "command": "npx",
              "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed"],
              "enabled": true
            },
            "sqlite": {
              "command": "uvx",
              "args": ["mcp-server-sqlite", "--db-path", "test.db"],
              "enabled": false
            }
          }
        }
    """
    import json as _json
    from pathlib import Path as _Path

    config_path = _Path(project_root) / ".mcp.json"
    if not config_path.exists():
        return []

    try:
        data = _json.loads(config_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        configs = []
        for name, cfg in servers.items():
            configs.append(MCPServerConfig(
                name=name,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                enabled=cfg.get("enabled", True),
            ))
        return configs
    except Exception as exc:
        logger.warning(".mcp.json 加载失败: %s", exc)
        return []
