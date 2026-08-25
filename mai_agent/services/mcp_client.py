"""MCP (Model Context Protocol) Client — JSON-RPC over stdio.

协议: https://spec.modelcontextprotocol.io
传输: stdio (子进程) 或 HTTP (SSE)

MCP 生命周期:
  1. 启动子进程 (stdio transport)
  2. initialize → 协商协议版本和能力
  3. tools/list → 获取可用工具列表
  4. tools/call → 调用工具
  5. 进程结束时发送 shutdown

对应 Claude Code 的 MCP client 实现。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """MCP 服务器配置 — 对应 .mcp.json 中的一个条目。"""
    name: str                          # 唯一标识，如 "filesystem"
    command: str                       # 启动命令，如 "npx"
    args: list[str] = field(default_factory=list)  # 命令参数
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class MCPToolDef:
    """MCP 工具定义（从 tools/list 返回）。"""
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""  # 来自哪个 MCP 服务器


class MCPClient:
    """MCP JSON-RPC 客户端 — 管理一个 MCP 服务器进程。

    Usage::

        client = MCPClient(config)
        await client.start()
        tools = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "/tmp/x.txt"})
        await client.stop()
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._capabilities: dict[str, Any] = {}
        self._running = False

    async def start(self) -> None:
        """启动 MCP 服务器进程并完成 initialize 握手。"""
        if self._running:
            return

        import os as _os
        import sys as _sys
        from shutil import which as _which
        env = {**_os.environ, **self.config.env,
               "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

        # Windows 兼容：subprocess 不解析 .cmd/.bat（npx/uvx 都是 .cmd shim），
        # 直接 exec 会 WinError 2。用 shutil.which 找 npx.cmd 等。
        command = self.config.command
        args = list(self.config.args)
        if _sys.platform == "win32":
            resolved = _which(command)
            if not resolved:
                resolved = _which(f"{command}.cmd")
            if resolved:
                command = resolved

        try:
            self._process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            logger.error("MCP 服务器 '%s' 启动失败: 命令 '%s' 未找到",
                        self.config.name, self.config.command)
            raise
        except Exception as exc:
            logger.error("MCP 服务器 '%s' 启动失败: %s", self.config.name, exc)
            raise

        self._running = True
        self._reader_task = asyncio.create_task(self._read_loop())
        # 必须排空 stderr，否则 server 写满 ~64KB 管道缓冲会永久阻塞（经典 PIPE 死锁）
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        try:
            # Initialize 握手
            result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "MAI-agent", "version": "0.2.0"},
            })
            self._capabilities = result.get("capabilities", {})
        except Exception:
            # initialize 失败 → 清理进程与任务，避免泄漏
            self._running = False
            for t in (self._reader_task, self._stderr_task):
                if t:
                    t.cancel()
            if self._process:
                try:
                    self._process.kill()
                except Exception:
                    pass
                self._process = None
            raise

        # 发送 initialized 通知
        await self._send_notification("notifications/initialized", {})
        logger.info("MCP '%s' 已连接 (协议 %s)", self.config.name,
                   result.get("protocolVersion", "?"))

    async def _read_loop(self) -> None:
        """后台读取 MCP 服务器的 stdout，解析 JSON-RPC 响应。"""
        assert self._process and self._process.stdout
        buffer = b""
        try:
            while self._running:
                chunk = await self._process.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                # MCP stdio 使用换行分隔的 JSON
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug("MCP 非 JSON 输出: %s", line[:100])
                        continue
                    # 处理响应（有 id 且无 method）；服务端发来的 request（有 id+method）不当作响应，
                    # 否则双方 id 都从 1 自增时会误取错结果 / 空结果
                    if ("id" in msg and msg["id"] is not None
                            and "method" not in msg):
                        fut = self._pending.pop(msg["id"], None)
                        if fut and not fut.done():
                            if "error" in msg:
                                fut.set_exception(
                                    MCPError(msg["error"].get("message", "Unknown")))
                            else:
                                fut.set_result(msg.get("result", {}))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("MCP '%s' 读取错误: %s", self.config.name, exc)

    async def _drain_stderr(self) -> None:
        """持续排空 stderr，防止子进程写满管道缓冲而阻塞。"""
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                chunk = await self._process.stderr.read(4096)
                if not chunk:
                    break
                logger.debug("MCP '%s' stderr: %s", self.config.name,
                             chunk.decode("utf-8", errors="replace").rstrip())
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _send_request(self, method: str, params: dict) -> dict:
        """发送 JSON-RPC 请求并等待响应。"""
        self._request_id += 1
        rid = self._request_id
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params,
        }, ensure_ascii=False)

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut

        assert self._process and self._process.stdin
        self._process.stdin.write((request + "\n").encode("utf-8"))
        await self._process.stdin.drain()

        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise MCPError(f"MCP 请求超时: {method}")

    async def _send_notification(self, method: str, params: dict) -> None:
        """发送 JSON-RPC 通知（无响应）。"""
        msg = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }, ensure_ascii=False)
        assert self._process and self._process.stdin
        self._process.stdin.write((msg + "\n").encode("utf-8"))
        await self._process.stdin.drain()

    async def list_tools(self) -> list[MCPToolDef]:
        """获取 MCP 服务器提供的工具列表。"""
        result = await self._send_request("tools/list", {})
        tools = result.get("tools", [])
        return [
            MCPToolDef(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=self.config.name,
            )
            for t in tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具并返回文本结果。"""
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        # MCP 返回 content 列表
        content = result.get("content", [])
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    texts.append(item.get("text", str(item)))
                else:
                    texts.append(str(item))
            return "\n".join(texts)
        return str(content)

    async def stop(self) -> None:
        """停止 MCP 服务器进程。"""
        self._running = False
        for t in (self._reader_task, self._stderr_task):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        if self._process:
            try:
                await self._send_notification("shutdown", {})
            except Exception:
                pass
            try:
                self._process.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._process.kill()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=3.0)
                except Exception:
                    pass
            self._process = None


class MCPError(Exception):
    """MCP 协议错误。"""
    pass
