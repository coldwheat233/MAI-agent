"""SendMessage — 对应 Claude Code 的 SendMessageTool。

多Agent协作中的通信桥梁。父Agent和子Agent通过此工具交换信息。
"""

from __future__ import annotations

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry


class SendMessageInput(ToolInput):
    to: str = Field(description="接收者名称 (如 'main' 发送给父Agent, 或子Agent名称)")
    summary: str = Field(description="消息摘要 (5-10字)")
    message: str = Field(description="消息正文")


class SendMessageTool(Tool):
    """Agent 间消息传递。

    Claude Code 对应物: SendMessageTool。
    子Agent完成任务后通过此工具把结果返回给父Agent。
    """
    name = "SendMessage"
    description = "向其他Agent发送消息。子Agent完成任务后向父Agent汇报，或Agent间协调。"
    input_schema = SendMessageInput
    is_concurrency_safe = False

    async def call(self, input: SendMessageInput, context: RunContext) -> str:
        # Store message in session state for retrieval by other agents
        inbox = context.session_state.setdefault("agent_inbox", [])
        inbox.append({
            "to": input.to,
            "from": "agent",
            "summary": input.summary,
            "message": input.message,
        })
        return f"Message sent to '{input.to}': {input.summary}"


registry.register(SendMessageTool())
