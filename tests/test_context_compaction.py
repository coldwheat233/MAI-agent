"""上下文压缩回归测试 — 覆盖"压缩拆散 tool 消息配对 → LLM 400"的卡死根因。

核心不变量：压缩后的消息列表里，每条 role=='tool' 消息前面必须紧跟一条
带 tool_calls 的 assistant 消息，且 tool_call_id 能对上。否则 DeepSeek 会拒绝：
"Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mai_agent.core.loop import _compact_context, _count_context_tokens
from mai_agent.core.models import (
    AssistantMessage,
    FunctionCall,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


class _SummaryLLM:
    """返回固定摘要的假 LLM —— _compact_context 只需 chat() 返回 .content。"""

    def __init__(self, content: str = "A summary of the middle segment."):
        self._content = content

    async def chat(self, messages, tools=None, **kw):
        return SimpleNamespace(content=self._content)


class _FailingLLM:
    """chat() 抛异常，验证压缩降级到简单截断。"""

    async def chat(self, messages, tools=None, **kw):
        raise RuntimeError("LLM down")


def _turn(i: int) -> list:
    """一轮对话：user → assistant(tool_calls) → tool → assistant(final)。"""
    return [
        UserMessage(content=f"task {i}"),
        AssistantMessage(
            content=None,
            tool_calls=[ToolCall(id=f"t{i}", function=FunctionCall(name="Read", arguments="{}"))],
        ),
        ToolResultMessage(content="file result", tool_call_id=f"t{i}", name="Read"),
        AssistantMessage(content=f"done {i}"),
    ]


def _has_orphan_tool(msgs) -> bool:
    """检测孤儿 tool 消息：tool 前面不是带匹配 tool_calls 的 assistant。"""
    for i, m in enumerate(msgs):
        if m.role != "tool":
            continue
        if i == 0:
            return True
        prev = msgs[i - 1]
        if prev.role != "assistant" or not prev.tool_calls:
            return True
        if not any(tc.id == m.tool_call_id for tc in prev.tool_calls):
            return True
    return False


@pytest.mark.asyncio
async def test_compact_preserves_tool_pairing():
    """压缩后不产生孤儿 tool 消息（直接回归之前的卡死根因）。"""
    msgs = [SystemMessage(content="sys")]
    for i in range(6):
        msgs.extend(_turn(i))

    compacted = await _compact_context(msgs, _SummaryLLM(), keep_last=8)

    # 关键断言：压缩后没有任何孤儿 tool 消息
    assert not _has_orphan_tool(compacted), "压缩产生了孤儿 tool 消息"


@pytest.mark.asyncio
async def test_compact_keeps_system_and_recent():
    """前导 system 消息保留，最近 keep_last 条消息完整保留。"""
    msgs = [SystemMessage(content="MAIN PROMPT")]
    for i in range(5):
        msgs.extend(_turn(i))

    compacted = await _compact_context(msgs, _SummaryLLM(), keep_last=8)

    # 第一条 system 保留
    assert compacted[0].role == "system"
    assert compacted[0].content == "MAIN PROMPT"
    # 最近一轮的最终回复保留（末尾是 assistant "done 4"）
    assert compacted[-1].role == "assistant"
    assert compacted[-1].content == "done 4"


@pytest.mark.asyncio
async def test_compact_recent_starts_on_turn_boundary():
    """切分点落在轮次边界：recent 区第一条是 user 消息，不从中途切。"""
    msgs = [SystemMessage(content="sys")]
    for i in range(6):
        msgs.extend(_turn(i))

    compacted = await _compact_context(msgs, _SummaryLLM(), keep_last=8)

    # 找到摘要 SystemMessage 后的第一条（即 recent 区的开头）
    # recent 区开头应为 user 消息（轮次边界），而不是 tool/assistant 半截
    recent_start_idx = None
    for idx, m in enumerate(compacted):
        if m.role == "system" and "摘要" in (m.content or ""):
            recent_start_idx = idx + 1
            break
    assert recent_start_idx is not None
    assert compacted[recent_start_idx].role == "user"


@pytest.mark.asyncio
async def test_compact_summary_llm_failure_falls_back():
    """摘要 LLM 失败时降级为简单截断，不抛异常、不产生孤儿 tool。"""
    msgs = [SystemMessage(content="sys")]
    for i in range(6):
        msgs.extend(_turn(i))

    compacted = await _compact_context(msgs, _FailingLLM(), keep_last=8)

    assert not _has_orphan_tool(compacted)
    # 降级摘要标记
    any_trunc = any(
        "截断" in (m.content or "") and m.role == "system" for m in compacted
    )
    assert any_trunc


@pytest.mark.asyncio
async def test_compact_noop_when_too_small():
    """消息太少时不压缩，原样返回。"""
    msgs = [SystemMessage(content="sys")] + _turn(0)  # 5 条，不足 keep_last+4
    result = await _compact_context(msgs, _SummaryLLM(), keep_last=8)
    assert result is msgs  # 直接返回原列表引用
