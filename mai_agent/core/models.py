"""消息、工具调用、会话状态的核心类型定义。

对应 Claude Code 的 types/message.ts + Tool.ts 中的类型定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


# ── 消息类型 ─────────────────────────────────────────────


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class SystemMessage(Message):
    role: str = "system"


@dataclass
class UserMessage(Message):
    role: str = "user"


@dataclass
class AssistantMessage(Message):
    role: str = "assistant"


@dataclass
class ToolResultMessage(Message):
    role: str = "tool"


# ── 工具调用 ─────────────────────────────────────────────


@dataclass
class FunctionCall:
    name: str
    arguments: str  # JSON string


@dataclass
class ToolCall:
    id: str
    type: str = "function"
    function: FunctionCall | None = None


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False


class ToolResult(BaseModel):
    """工具执行结果（Pydantic，序列化友好）"""
    tool_use_id: str
    content: str
    is_error: bool = False


# ── 权限 ─────────────────────────────────────────────────


@dataclass
class PermissionResult:
    allow: bool
    reason: str = ""
    modified_input: dict[str, Any] | None = None


class PermissionMode(str, Enum):
    AUTO = "auto"             # 完全自动
    MANUAL = "manual"         # 每次手动确认
    PLAN = "plan"             # Plan模式 — 规划后确认再执行


# ── Agent定义 ─────────────────────────────────────────────


@dataclass
class AgentDefinition:
    """子Agent的定义 — 对应 Claude Code 的 .claude/agents/*.md"""
    name: str
    description: str
    prompt: str                    # System prompt
    allowed_tools: list[str]       # 工具白名单
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None       # 强制模型
    isolation: Literal["none", "worktree"] = "none"


@dataclass
class AgentOutput:
    """子Agent的返回结果"""
    agent_id: str
    content: str
    total_tokens: int = 0
    tool_calls: int = 0
    status: Literal["completed", "failed", "cancelled"] = field(default="completed")
