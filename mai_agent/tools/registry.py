"""工具注册表 — 对应 Claude Code 的 tools.ts。

集中管理所有工具的注册、查找、以及 Feature Flag 控制的可见性过滤。
"""

from __future__ import annotations

import logging
from typing import Optional

from mai_agent.tools.base import Tool, ToolResult, RunContext

logger = logging.getLogger(__name__)


class ToolRegistry:
    """全局工具注册表。

    Claude Code 对应物: tools.ts 中的 Tools 类型和注册逻辑。

    功能:
      - register(tool) → 注册工具
      - get(name) → 按名查找
      - get_all(mode) → 按模式过滤可见工具
      - to_openai_schemas(mode) → 转 OpenAI function calling 格式
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._feature_flags: dict[str, set[str]] = {}  # mode → {tool_names}

    def register(self, tool: Tool, modes: Optional[list[str]] = None) -> None:
        """注册一个工具。

        Args:
            tool: 工具实例
            modes: 此工具在哪些模式下可见。None = 所有模式。
                   例如 ['auto', 'manual', 'plan']
        """
        if tool.name in self._tools:
            raise ValueError(f"工具名称冲突: {tool.name}")

        self._tools[tool.name] = tool

        if modes is None:
            modes = ["auto", "manual", "plan"]
        for mode in modes:
            if mode not in self._feature_flags:
                self._feature_flags[mode] = set()
            self._feature_flags[mode].add(tool.name)

        logger.debug("工具已注册: %s (modes=%s, concurrent=%s)",
                     tool.name, modes, tool.is_concurrency_safe)

    def get(self, name: str) -> Tool:
        """按名查找工具，未找到抛出 KeyError。"""
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def get_visible(self, mode: str = "auto") -> list[Tool]:
        """返回指定模式下可见的工具列表。"""
        visible_names = self._feature_flags.get(mode, set())
        return [self._tools[n] for n in visible_names if n in self._tools]

    def to_openai_schemas(self, mode: str = "auto") -> list[dict]:
        """转为 OpenAI function calling 的 tools 参数。"""
        return [t.to_openai_schema() for t in self.get_visible(mode)]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)


# ── 全局单例 ─────────────────────────────────────────────

registry = ToolRegistry()
"""全局工具注册表单例。所有工具通过 import registry 来注册。"""
