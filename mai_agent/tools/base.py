"""工具基类 — 对应 Claude Code 的 Tool.ts。

每个工具由三部分组成:
  1. Pydantic Input Schema → 类型安全的参数校验
  2. Tool 实例 → name/description/is_concurrency_safe
  3. call() 方法 → 实际执行逻辑
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel


class ToolInput(BaseModel):
    """工具参数的基类。每个具体工具继承此类定义自己的参数 schema。"""
    model_config = {"extra": "forbid"}


class ToolResult(BaseModel):
    """工具执行结果"""
    tool_use_id: str
    content: str
    is_error: bool = False
    duration_ms: float = 0


@dataclass
class RunContext:
    """工具执行上下文 — 对应 Claude Code 的 ToolUseContext。

    工具通过 context 访问：
    - 当前工作目录
    - 会话状态（跨轮次共享的 dict）
    - 文件状态缓存
    - 中断信号
    - stream_callback: 工具可调用来实时推送输出（如 Bash stdout）
    """

    cwd: str = "."
    session_state: dict[str, Any] = field(default_factory=dict)
    permission_mode: str = "auto"  # auto | manual | plan
    active_brain: str = ""  # 当前激活的脑（空=无），如 "dev_explorer" / "dev_validator"
    abort_signal: Optional[Any] = None  # asyncio.Event or threading.Event
    stream_callback: Any = None  # async fn(text: str) -> None

    def is_aborted(self) -> bool:
        if self.abort_signal is None:
            return False
        try:
            return self.abort_signal.is_set()
        except Exception:
            return False


class Tool(ABC):
    """工具基类 — 所有工具必须继承此类。

    Claude Code 对应物: Tool.ts 中的 Tool interface.

    子类需要:
      1. 定义 name / description / input_schema
      2. 实现 call() 方法
      3. 可选覆盖 is_concurrency_safe (默认 False)
    """

    name: str = ""
    description: str = ""
    input_schema: type[ToolInput] = ToolInput
    is_concurrency_safe: bool = False
    """True: 此工具是只读的，可以与其他只读工具并发执行。
    False: 此工具有写操作，必须串行执行。
    对应 Claude Code 的 partitionToolCalls() 逻辑。"""

    async def execute(self, args: dict[str, Any], context: RunContext) -> ToolResult:
        """完整的工具执行管道：
        1. 校验参数 (Pydantic)
        2. 记录开始时间
        3. 调用 call()
        4. 包装结果为 ToolResult
        """
        tool_use_id = args.pop("_tool_use_id", str(uuid.uuid4())[:8])
        start = time.perf_counter()

        try:
            validated = self.input_schema(**args)
            content = await self.call(validated, context)
            is_error = content.startswith("[ERROR]")
        except Exception as exc:
            content = f"[ERROR] {type(exc).__name__}: {exc}"
            is_error = True

        elapsed = (time.perf_counter() - start) * 1000
        return ToolResult(
            tool_use_id=tool_use_id,
            content=str(content),
            is_error=is_error,
            duration_ms=elapsed,
        )

    @abstractmethod
    async def call(self, input: ToolInput, context: RunContext) -> str:
        """子类实现具体的工具逻辑。返回字符串结果。"""
        ...

    def to_openai_schema(self) -> dict[str, Any]:
        """将工具转换为 OpenAI function calling 格式。

        对应 Claude Code 的 tools_schema 构建逻辑。
        """
        schema = self.input_schema.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        }
