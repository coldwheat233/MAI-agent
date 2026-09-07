---
name: mai-mcp
description: MCP 接入 Skill。McpTool 懒加载代理、.mcp.json 与 Plugin mcp_config 合并、stdio JSON-RPC client。
whenToUse: 接新 MCP server / 改 .mcp.json / MCP 协议或 client / McpTool 代理
---

# mai-mcp

外部 MCP（Model Context Protocol）服务器接入。

## 关键位置

- `tools/mcp_tools.py`：
  - `McpTool` 代理工具（常驻注册）：`action=list` 列工具 / `action=call` 按 `server::tool` 调用
  - `load_mcp_config(root)` — 合并 `.mcp.json` + Plugin 的 `mcp_config.json`（`.mcp.json` 同名优先）
  - `start_mcp_servers(configs)` / `stop_all_mcp()` — 启动并把工具定义缓存进 `_tool_cache`
- `services/mcp_client.py` — `MCPClient`（stdio 子进程 JSON-RPC）

## 语义（为什么只有 1 个代理工具）

- 懒加载：不把每个 MCP 工具注册成独立 Tool（14 工具 ≈ 6K tokens/轮 schema）
- 只注册 `McpTool`：模型先 `list` 再 `call`，固定上下文 ~300 tokens
- 工具缓存 key：`{server_name}::{tool_name}`；工具名全局唯一时可不带 server 调用

## 红线

- **不要给 MCP 工具逐个注册独立 Tool**——会毁掉懒加载省上下文的收益
- `enabled=false` 的 server 不启动（.mcp.json 与 plugin mcp_config 都认该字段）
- 同 server 已在运行时跳过重复启动
- 原生能力已覆盖的场景默认关 MCP 避免冗余：FileRead/FileWrite vs filesystem、SQLite 直连 vs mcp-sqlite（协议层通即可，`enabled` 改 true 就能接）
- Plugin 注册的 mcp server 走 `plugins.loader.get_plugin_mcp_servers()`，勿在 mcp_tools 里重复实现

## 边界

- 外部 server 的具体工具逻辑 → 各 MCP server 自己的仓库
