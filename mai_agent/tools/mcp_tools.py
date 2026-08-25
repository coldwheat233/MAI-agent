"""MCP 工具适配器 — 将外部 MCP 服务器的工具暴露给 MAI-agent。

懒加载设计（解决工具 schema 占上下文）:
  - 不把每个 MCP 工具注册成独立 Tool（14 个工具 = 14 份 schema 注入 LLM，~6K tokens/轮）
  - 只注册 1 个代理工具 McpTool: 模型先用它"列出可用工具"，再按名"调用"
  - 代价: 实际调用多一次 list（~200 tokens）；收益: 固定上下文 6K → ~300 tokens
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry
from mai_agent.services.mcp_client import MCPClient, MCPServerConfig, MCPToolDef

logger = logging.getLogger(__name__)

# 全局 MCP 客户端管理
_mcp_clients: dict[str, MCPClient] = {}
# 工具缓存: (server_name, tool_name) → MCPToolDef（供代理工具按名调用）
_tool_cache: dict[str, MCPToolDef] = {}


class McpToolInput(ToolInput):
    """代理工具的输入：列出 or 调用。"""
    action: str = Field(
        default="call",
        description="'list'（列出所有可用 MCP 工具）或 'call'（调用指定工具）",
    )
    server: str = Field(default="", description="MCP 服务器名（list 时可为空=全部）")
    tool: str = Field(default="", description="要调用的 MCP 工具名（action=call 时必填，如 'read_text_file'）")
    arguments: str = Field(
        default="{}",
        description="JSON-encoded 工具参数，如 '{\"path\": \"/tmp/x.txt\"}'",
    )


class McpTool(Tool):
    """MCP 代理工具 — 列表 + 调用的统一入口（懒加载）。

    模型流程:
      1. 先调 action=list 看有哪些可用工具（含 server 名 + 工具名 + 描述）
      2. 再调 action=call, server=<s>, tool=<t>, arguments=<json> 执行
    """
    name = "McpTool"
    description = (
        "调用已连接的 MCP（Model Context Protocol）服务器工具。"
        "MCP 服务器提供外部系统能力（文件系统/数据库/浏览器等）。"
        "用法: 先 action=list 查看可用工具，再 action=call 调用指定工具。"
        "参数: server=MCP服务器名, tool=工具名, arguments=JSON参数。"
    )
    input_schema = McpToolInput
    is_concurrency_safe = False  # MCP 调用有外部副作用，串行保守

    async def call(self, input: McpToolInput, context: RunContext) -> str:
        if input.action == "list":
            return self._list_tools(input.server)

        # call
        if not input.tool:
            return "[ERROR] action=call 时需要 tool 参数。先 action=list 查看可用工具。"
        key = f"{input.server}::{input.tool}"
        tool_def = _tool_cache.get(key)
        if tool_def is None:
            # 尝试不指定 server（工具名全局唯一时）
            matches = [td for k, td in _tool_cache.items() if k.endswith(f"::{input.tool}")]
            if len(matches) == 1:
                tool_def = matches[0]
            elif not matches:
                return f"[ERROR] 未找到 MCP 工具: {input.tool}。可用工具见 action=list。"
            else:
                return f"[ERROR] 工具 '{input.tool}' 存在于多个服务器，需指定 server 参数。"
        try:
            args = json.loads(input.arguments or "{}")
        except json.JSONDecodeError:
            return f"[ERROR] 无效的 JSON arguments: {input.arguments}"
        client = _mcp_clients.get(tool_def.server_name)
        if client is None:
            return f"[ERROR] MCP 服务器未运行: {tool_def.server_name}"
        try:
            return await client.call_tool(tool_def.name, args)
        except Exception as exc:
            return f"[ERROR] MCP 工具 '{tool_def.name}' 执行失败: {exc}"

    def _list_tools(self, server: str = "") -> str:
        """列出可用 MCP 工具（按服务器分组）。"""
        if not _tool_cache:
            return "当前没有已连接的 MCP 工具。检查 .mcp.json 配置。"
        lines = [f"可用 MCP 工具 ({len(_tool_cache)}):"]
        for key, td in sorted(_tool_cache.items()):
            srv, tname = key.split("::", 1)
            if server and srv != server:
                continue
            desc = (td.description or "")[:100].replace("\n", " ")
            lines.append(f"  [{srv}] {tname} — {desc}")
        return "\n".join(lines)


# 注册代理工具（全局唯一，常驻）
registry.register(McpTool())


# ── MCP 服务管理器 ───────────────────────────────────────


async def start_mcp_servers(configs: list[MCPServerConfig]) -> int:
    """启动所有 MCP 服务器并缓存其工具定义（不注册独立工具，走懒加载）。

    Args:
        configs: MCP 服务器配置列表

    Returns:
        缓存了多少个 MCP 工具定义
    """
    count = 0
    for cfg in configs:
        if not cfg.enabled:
            continue
        if cfg.name in _mcp_clients:
            logger.info("MCP '%s' 已在运行，跳过", cfg.name)
            continue
        try:
            client = MCPClient(cfg)
            await client.start()
            tools = await client.list_tools()
            _mcp_clients[cfg.name] = client

            for td in tools:
                key = f"{cfg.name}::{td.name}"
                _tool_cache[key] = td
                count += 1
                logger.info("MCP 工具已缓存: %s (%s)", key, td.description[:60])

            logger.info("MCP '%s': %d 个工具已缓存（懒加载，未注入 schema）", cfg.name, len(tools))
        except Exception as exc:
            logger.warning("MCP '%s' 启动失败: %s", cfg.name, exc)

    return count


async def stop_all_mcp() -> None:
    """停止所有 MCP 服务器并清理缓存。"""
    for name, client in list(_mcp_clients.items()):
        try:
            await client.stop()
        except Exception as exc:
            logger.warning("MCP '%s' 停止失败: %s", name, exc)
    _mcp_clients.clear()
    _tool_cache.clear()
    # 保留 McpTool 代理工具本身（常驻 registry）


def load_mcp_config(project_root: str = ".") -> list[MCPServerConfig]:
    """从 .mcp.json 加载 MCP 服务器配置。"""
    from pathlib import Path as _Path

    config_path = _Path(project_root) / ".mcp.json"
    if not config_path.exists():
        return []

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
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
