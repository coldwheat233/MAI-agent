"""Tests for tool system: registry, base, orchestration, file tools."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext, ToolResult
from mai_agent.tools.registry import ToolRegistry
from mai_agent.tools.orchestration import (
    ToolUseBlock,
    run_tools,
    partition_by_safety,
)


# ── Tool Registry ────────────────────────────────────────


class _FakeInput(ToolInput):
    x: int = Field(description="number")


class _ReadOnlyTool(Tool):
    name = "TestRead"
    description = "test"
    input_schema = _FakeInput
    is_concurrency_safe = True

    async def call(self, input, ctx):
        return str(input.x * 2)


class _WriteTool(Tool):
    name = "TestWrite"
    description = "test"
    input_schema = _FakeInput
    is_concurrency_safe = False

    async def call(self, input, ctx):
        return f"wrote {input.x}"


def test_registry_register_and_get():
    reg = ToolRegistry()
    reg.register(_ReadOnlyTool())
    assert reg.has("TestRead")
    assert reg.get("TestRead").is_concurrency_safe
    assert len(reg) == 1


def test_registry_duplicate_raises():
    reg = ToolRegistry()
    reg.register(_ReadOnlyTool())
    with pytest.raises(ValueError, match="冲突"):
        reg.register(_ReadOnlyTool())


def test_registry_get_missing():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("Nonexistent")


def test_registry_modes():
    reg = ToolRegistry()
    reg.register(_ReadOnlyTool(), modes=["auto", "plan"])
    reg.register(_WriteTool(), modes=["auto"])

    assert len(reg.get_visible("auto")) == 2
    assert len(reg.get_visible("plan")) == 1  # Only read
    assert len(reg.get_visible("manual")) == 0


def test_registry_to_openai_schemas():
    reg = ToolRegistry()
    reg.register(_ReadOnlyTool())
    schemas = reg.to_openai_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "TestRead"
    assert "properties" in schemas[0]["function"]["parameters"]


# ── Tool Base ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_execute_valid():
    tool = _ReadOnlyTool()
    result = await tool.execute({"x": 5, "_tool_use_id": "abc"}, RunContext())
    assert result.content == "10"
    assert not result.is_error
    assert result.tool_use_id == "abc"


@pytest.mark.asyncio
async def test_tool_execute_invalid_input():
    tool = _ReadOnlyTool()
    result = await tool.execute({"x": "not_a_number"}, RunContext())
    assert result.is_error
    assert "ERROR" in result.content or "error" in result.content.lower()


@pytest.mark.asyncio
async def test_tool_execute_duration():
    tool = _ReadOnlyTool()
    result = await tool.execute({"x": 3}, RunContext())
    assert result.duration_ms >= 0


# ── Orchestration ────────────────────────────────────────


def test_partition_by_safety():
    reg = ToolRegistry()
    reg.register(_ReadOnlyTool())
    reg.register(_WriteTool())

    blocks = [
        ToolUseBlock(id="1", name="TestRead", input={"x": 1}),
        ToolUseBlock(id="2", name="TestWrite", input={"x": 2}),
        ToolUseBlock(id="3", name="TestRead", input={"x": 3}),
        ToolUseBlock(id="4", name="Nonexistent", input={}),  # Default: serial
    ]

    concurrent, serial = partition_by_safety(blocks, reg)
    assert len(concurrent) == 2  # Two reads
    assert len(serial) == 2      # One write + one unknown


@pytest.mark.asyncio
async def test_run_tools_concurrent_and_serial():
    reg = ToolRegistry()
    reg.register(_ReadOnlyTool())
    reg.register(_WriteTool())

    blocks = [
        ToolUseBlock(id="1", name="TestRead", input={"x": 1}),
        ToolUseBlock(id="2", name="TestRead", input={"x": 2}),
        ToolUseBlock(id="3", name="TestWrite", input={"x": 3}),
    ]

    results = []
    async for r in run_tools(blocks, reg, RunContext()):
        results.append(r)

    assert len(results) == 3
    # Reads (concurrent) should have run, then Write (serial)
    contents = [r.message.content for r in results]
    assert "2" in contents  # 1*2
    assert "4" in contents  # 2*2
    assert any("wrote" in c for c in contents)


# ── File Tools ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_file_read(temp_dir):
    from mai_agent.tools.file_read import FileReadTool
    path = Path(temp_dir) / "test.txt"
    path.write_text("line one\nline two\nline three", encoding="utf-8")

    tool = FileReadTool()
    ctx = RunContext(cwd=temp_dir)

    result = await tool.execute({
        "file_path": str(path),
        "_tool_use_id": "r1",
    }, ctx)
    assert "line one" in result.content
    assert not result.is_error

    # Test with offset + limit
    result2 = await tool.execute({
        "file_path": str(path),
        "offset": 2,
        "limit": 1,
        "_tool_use_id": "r2",
    }, ctx)
    assert "line two" in result2.content
    assert "line one" not in result2.content or "2\t" in result2.content


@pytest.mark.asyncio
async def test_file_read_nonexistent():
    from mai_agent.tools.file_read import FileReadTool
    tool = FileReadTool()
    result = await tool.execute({
        "file_path": "/nonexistent/path.txt",
    }, RunContext())
    assert result.is_error


@pytest.mark.asyncio
async def test_file_write(temp_dir):
    from mai_agent.tools.file_write import FileWriteTool
    tool = FileWriteTool()
    ctx = RunContext(cwd=temp_dir)

    result = await tool.execute({
        "file_path": str(Path(temp_dir) / "out.txt"),
        "content": "hello world\nhello again",
    }, ctx)

    assert not result.is_error
    assert (Path(temp_dir) / "out.txt").read_text() == "hello world\nhello again"


@pytest.mark.asyncio
async def test_file_edit(temp_dir):
    from mai_agent.tools.file_edit import FileEditTool
    path = Path(temp_dir) / "edit_me.txt"
    path.write_text("original content here", encoding="utf-8")

    tool = FileEditTool()
    ctx = RunContext(cwd=temp_dir)

    result = await tool.execute({
        "file_path": str(path),
        "old_string": "original",
        "new_string": "modified",
        "replace_all": False,
    }, ctx)

    assert not result.is_error
    assert "modified content here" == path.read_text()


@pytest.mark.asyncio
async def test_file_edit_not_found(temp_dir):
    from mai_agent.tools.file_edit import FileEditTool
    path = Path(temp_dir) / "edit_me.txt"
    path.write_text("hello", encoding="utf-8")

    tool = FileEditTool()
    ctx = RunContext(cwd=temp_dir)

    result = await tool.execute({
        "file_path": str(path),
        "old_string": "nonexistent text",
        "new_string": "x",
        "replace_all": False,
    }, ctx)
    assert result.is_error


@pytest.mark.asyncio
async def test_file_edit_diff_display(temp_dir):
    from mai_agent.tools.file_edit import FileEditTool
    path = Path(temp_dir) / "d.txt"
    path.write_text("old", encoding="utf-8")

    tool = FileEditTool()
    result = await tool.execute({
        "file_path": str(path), "old_string": "old", "new_string": "new",
    }, RunContext(cwd=temp_dir))

    assert "- old" in result.content
    assert "+ new" in result.content


# ── Full registry test ───────────────────────────────────


def test_all_tools_have_schema(full_registry):
    """Every registered tool must have a name, description, and valid schema."""
    for name in full_registry.names():
        tool = full_registry.get(name)
        assert tool.name, f"{name}: empty name"
        assert tool.description, f"{name}: empty description"
        assert tool.input_schema, f"{name}: no input schema"
        schema = tool.to_openai_schema()
        assert "function" in schema
        assert schema["function"]["name"] == name
