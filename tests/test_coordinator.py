"""Tests for coordinator verdict parsing and state machine."""

from mai_agent.brains.coordinator import parse_verdict, BrainState


def test_parse_closed():
    state, items = parse_verdict("闭合状态: CLOSED. 所有测试通过。")
    assert state == BrainState.COMPLETED
    assert items == []


def test_parse_closed_english():
    state, items = parse_verdict("Logical closure: CLOSED. All passes.")
    assert state == BrainState.COMPLETED


def test_parse_open_with_items():
    output = """闭合状态: OPEN
未完成项:
- item1: user auth not done
- item2: tests missing
"""
    state, items = parse_verdict(output)
    assert state == BrainState.BLOCKED
    assert len(items) >= 1


def test_parse_blocked_signal():
    state, _ = parse_verdict("Tests failed: 3/5 passed. Blocked on auth.")
    assert state == BrainState.BLOCKED


def test_parse_empty():
    state, items = parse_verdict("some random text with no clear signal")
    # Default: if no clear signal, assume completed
    assert state == BrainState.COMPLETED
    assert items == []


def test_parse_all_passed_chinese():
    state, items = parse_verdict("全部通过，没有遗留问题")
    assert state == BrainState.COMPLETED
