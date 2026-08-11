"""Tests for session memory threshold logic."""

from mai_agent.core.models import (
    Message, SystemMessage, UserMessage, AssistantMessage,
    ToolCall, FunctionCall,
)
from mai_agent.services.memory import (
    should_extract, reset_state, set_config,
    _estimate_tokens, _count_tool_calls_since,
    _last_turn_has_pending_tools,
)


def _make_msgs(tool_count: int = 0, content_len: int = 1000) -> list[Message]:
    """Build a realistic message list for testing."""
    msgs: list[Message] = [
        SystemMessage(content="x" * (content_len // 2)),
        UserMessage(content="x" * (content_len // 2)),
    ]
    for i in range(tool_count):
        tc = ToolCall(id=str(i), function=FunctionCall(name="Read", arguments='{"path": "/f"}'))
        msgs.append(AssistantMessage(content="", tool_calls=[tc]))
        msgs.append(Message(role="tool", content="x" * 100))
    return msgs


def test_reset_state():
    reset_state()
    msgs = _make_msgs(0, 200)  # Not enough tokens
    assert not should_extract(msgs)


def test_init_threshold():
    reset_state()
    set_config(min_tokens_to_init=500)
    # 1000 chars = ~250 tokens — below 500
    msgs = _make_msgs(0, 1000)
    result = should_extract(msgs)
    assert not result  # Not enough tokens to init


def test_init_threshold_met():
    reset_state()
    set_config(min_tokens_to_init=400, min_tokens_between_update=100, tool_calls_between_update=2)
    # ~2500 chars = ~625 tokens — above 400 init
    msgs = _make_msgs(3, 2500)
    result = should_extract(msgs)
    assert result  # After init + 3 tools, should extract


def test_tool_count_threshold_not_met():
    reset_state()
    set_config(min_tokens_to_init=400, min_tokens_between_update=100, tool_calls_between_update=5)
    msgs = _make_msgs(3, 2500)  # Only 3 tools, need 5
    result = should_extract(msgs)
    assert not result


def test_safe_window_blocks_extraction():
    reset_state()
    set_config(min_tokens_to_init=400, min_tokens_between_update=100, tool_calls_between_update=1)
    msgs = _make_msgs(2, 2500)
    # Last message is tool result, but we have no pending tools
    assert not _last_turn_has_pending_tools(msgs)

    # Add assistant with tool_call at end — now pending
    tc = ToolCall(id="99", function=FunctionCall(name="Bash", arguments="{}"))
    msgs.append(AssistantMessage(content="", tool_calls=[tc]))
    # No tool result after this assistant → pending
    assert _last_turn_has_pending_tools(msgs)
    # So extraction should be blocked
    assert not should_extract(msgs)


def test_estimate_tokens():
    msgs = [
        SystemMessage(content="hello world"),  # 11 chars → 2 tokens
        UserMessage(content="x" * 100),  # 100 chars → 25 tokens
    ]
    assert _estimate_tokens(msgs) == 111 // 4  # ~27


def test_count_tool_calls_since():
    msgs = _make_msgs(4, 1000)
    # All tool calls are after index -1 (all messages)
    count = _count_tool_calls_since(msgs, -1)
    assert count == 4
    # After index 2, there should be fewer
    count2 = _count_tool_calls_since(msgs, 5)  # After first 2 tool calls (index 5 roughly)
    assert count2 < 4


def test_double_extraction_blocked_by_token_delta():
    """After first extraction, second is blocked until enough new tokens.

    This simulates the actual extraction cycle: should_extract → extraction → should_extract.
    Between calls, _tokens_at_last_extraction is updated (as extract_and_persist would do).
    """
    from mai_agent.services.memory import _estimate_tokens

    reset_state()
    set_config(min_tokens_to_init=300, min_tokens_between_update=500, tool_calls_between_update=2)

    msgs = _make_msgs(3, 2000)
    # First call: should extract
    assert should_extract(msgs)

    # Simulate extraction completion — update token threshold
    import mai_agent.services.memory as mem
    mem._tokens_at_last_extraction = _estimate_tokens(msgs)
    mem._last_extraction_index = len(msgs) - 1

    # Same messages, no new tokens → should NOT extract
    assert not should_extract(msgs)
