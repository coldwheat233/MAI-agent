"""Integration tests — mock LLM for deterministic testing of the agent loop."""

import pytest

from mai_agent.core.loop import (
    agent_loop, AgentLoopConfig, messages_to_openai, StepProgress,
)
from mai_agent.core.models import SystemMessage, UserMessage
from mai_agent.tools.base import RunContext, Tool, ToolInput
from mai_agent.tools.registry import ToolRegistry


class _MockReadTool(Tool):
    name = "Read"
    description = "Read files"
    input_schema = ToolInput
    is_concurrency_safe = True

    async def call(self, input, ctx):
        return "file content: hello world"


# ── Message conversion ───────────────────────────────────


def test_messages_to_openai():
    msgs = [
        SystemMessage(content="you are helpful"),
        UserMessage(content="read file"),
    ]
    openai_msgs = messages_to_openai(msgs)
    assert len(openai_msgs) == 2
    assert openai_msgs[0]["role"] == "system"
    assert openai_msgs[1]["role"] == "user"
    assert openai_msgs[0]["content"] == "you are helpful"


# ── Agent loop with mock LLM ─────────────────────────────


@pytest.mark.asyncio
async def test_agent_loop_converges_directly():
    """LLM returns text without tool calls → loop exits immediately."""
    reg = ToolRegistry()
    reg.register(_MockReadTool())

    class MockLLM:
        async def chat_stream(self, messages, tools=None, **kw):
            yield ("The answer is 42.", None, None)
            yield (None, None, "stop")

        @property
        def model(self):
            return "mock"

    answer, messages = await agent_loop(
        user_input="what is the answer?",
        llm=MockLLM(),
        registry=reg,
        context=RunContext(),
        config=AgentLoopConfig(max_turns=5),
    )
    assert "42" in answer
    assert len(messages) >= 3  # system + user + assistant


@pytest.mark.asyncio
async def test_agent_loop_tool_then_converge():
    """LLM calls a tool, then after results, returns text."""
    reg = ToolRegistry()
    reg.register(_MockReadTool())

    call_count = [0]

    class MockLLM:
        async def chat_stream(self, messages, tools=None, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                from mai_agent.llm.client import ToolCall as LLMToolCall, FunctionCall
                tc = LLMToolCall(id="t1", function=FunctionCall(name="Read", arguments='{"file_path": "/f"}'))
                yield (None, [tc], "stop")
            else:
                yield ("File says: hello world", None, None)
                yield (None, None, "stop")

    progress_events = []

    async def track_progress(p: StepProgress):
        progress_events.append(p)

    answer, messages = await agent_loop(
        user_input="read the file",
        llm=MockLLM(),
        registry=reg,
        context=RunContext(),
        config=AgentLoopConfig(max_turns=5),
        on_progress=track_progress,
    )

    assert "hello world" in answer
    events = [e.event for e in progress_events]
    assert "thinking" in events
    assert "converge" in events


@pytest.mark.asyncio
async def test_agent_loop_max_turns():
    """Agent hits max_turns → returns fallback message."""
    reg = ToolRegistry()
    reg.register(_MockReadTool())

    class MockLLM:
        async def chat_stream(self, messages, tools=None, **kw):
            from mai_agent.llm.client import ToolCall as LLMToolCall, FunctionCall
            tc = LLMToolCall(id="t1", function=FunctionCall(name="Read", arguments='{"file_path": "/f"}'))
            yield (None, [tc], "stop")

    answer, _ = await agent_loop(
        user_input="loop forever",
        llm=MockLLM(),
        registry=reg,
        context=RunContext(),
        config=AgentLoopConfig(max_turns=3),
    )
    assert "limit" in answer.lower() or "step" in answer.lower()


