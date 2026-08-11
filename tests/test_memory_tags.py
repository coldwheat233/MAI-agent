"""Tests for the tagged memory system + worktree tools."""

import json
import os

import pytest

from mai_agent.services import memory_tags
from mai_agent.services.memory_tags import TaggedMemory


# ── Tagged Memory ────────────────────────────────────────


def test_save_and_load_memory(temp_dir):
    mem = TaggedMemory(
        name="distributed-lock",
        description="分布式锁选型",
        type="reference",
        tags=["并发", "后端"],
        content="Redis Redlock 优于 ZK 在性能。详见 [[redis]]",
    )
    path = memory_tags.save_memory(mem, temp_dir)

    assert os.path.exists(path)
    loaded = memory_tags.load_memory_by_name("distributed-lock", temp_dir)
    assert loaded is not None
    assert loaded.description == "分布式锁选型"
    assert loaded.type == "reference"
    assert "并发" in loaded.tags
    assert "redis" in loaded.wiki_links()


def test_index_rebuilt_on_save(temp_dir):
    memory_tags.save_memory(
        TaggedMemory(name="a", description="alpha", tags=["x"]), temp_dir,
    )
    memory_tags.save_memory(
        TaggedMemory(name="b", description="beta", tags=["x", "y"]), temp_dir,
    )

    idx = memory_dir_text(temp_dir)
    assert "[a]" in idx
    assert "[b]" in idx

    tag_index = memory_tags.load_tag_index(temp_dir)
    assert "x" in tag_index
    assert set(tag_index["x"]) == {"a", "b"}
    assert tag_index["y"] == ["b"]


def memory_dir_text(project_root):
    return memory_tags.index_path(project_root).read_text(encoding="utf-8")


def test_search_by_tag(temp_dir):
    memory_tags.save_memory(
        TaggedMemory(name="a", description="alpha", tags=["py"]), temp_dir,
    )
    memory_tags.save_memory(
        TaggedMemory(name="b", description="beta", tags=["rust"]), temp_dir,
    )
    results = memory_tags.search_by_tag("py", temp_dir)
    assert len(results) == 1
    assert results[0].name == "a"


def test_search_fulltext(temp_dir):
    memory_tags.save_memory(
        TaggedMemory(name="a", description="redis cache", content="LRU eviction"),
        temp_dir,
    )
    results = memory_tags.search("LRU", temp_dir)
    assert len(results) == 1
    assert results[0].name == "a"


def test_resolve_wikilinks(temp_dir):
    memory_tags.save_memory(
        TaggedMemory(name="redis", description="in-memory store"), temp_dir,
    )
    text = "use [[redis]] for caching, [[unknown]] stays"
    resolved = memory_tags.resolve_wikilinks(text, temp_dir)
    assert "redis: in-memory store" in resolved
    assert "[[unknown]]" in resolved  # unlinked preserved


def test_related_memories(temp_dir):
    memory_tags.save_memory(
        TaggedMemory(name="a", description="alpha", content="see [[b]]"), temp_dir,
    )
    memory_tags.save_memory(
        TaggedMemory(name="b", description="beta", content="standalone"), temp_dir,
    )
    related = memory_tags.related_memories("a", temp_dir)
    assert len(related) == 1
    assert related[0].name == "b"

    # reverse: b is referenced by a
    related_b = memory_tags.related_memories("b", temp_dir)
    assert any(r.name == "a" for r in related_b)


def test_delete_memory(temp_dir):
    memory_tags.save_memory(
        TaggedMemory(name="tmp", description="temp"), temp_dir,
    )
    assert memory_tags.delete_memory("tmp", temp_dir) is True
    assert memory_tags.load_memory_by_name("tmp", temp_dir) is None
    assert memory_tags.delete_memory("tmp", temp_dir) is False


def test_tagged_memory_context_injection(temp_dir):
    memory_tags.save_memory(
        TaggedMemory(name="x", description="desc x", tags=["t"]), temp_dir,
    )
    ctx = memory_tags.tagged_memory_context(temp_dir)
    assert "Tagged Memories" in ctx
    assert "[[x]]" in ctx


def test_invalid_type_defaults_to_reference(temp_dir):
    mem = TaggedMemory(name="bad", description="d", type="nonsense", content="c")
    memory_tags.save_memory(mem, temp_dir)
    loaded = memory_tags.load_memory_by_name("bad", temp_dir)
    assert loaded.type == "reference"


# ── Memory tools ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_write_and_search_tools(temp_dir):
    from mai_agent.tools.memory_tools import MemoryWriteTool, MemorySearchTool
    from mai_agent.tools.base import RunContext

    ctx = RunContext(cwd=temp_dir, session_state={"project_root": temp_dir})

    w = MemoryWriteTool()
    res = await w.execute({
        "name": "k8s",
        "description": "k8s 基础",
        "content": "pod 是最小调度单元 [[container]]",
        "type": "reference",
        "tags": ["devops", "k8s"],
    }, ctx)
    assert not res.is_error
    assert "k8s" in res.content

    s = MemorySearchTool()
    res2 = await s.execute({"tag": "devops"}, ctx)
    assert not res2.is_error
    assert "k8s" in res2.content


@pytest.mark.asyncio
async def test_memory_read_resolves_links(temp_dir):
    from mai_agent.tools.memory_tools import MemoryReadTool, MemoryWriteTool
    from mai_agent.tools.base import RunContext

    ctx = RunContext(cwd=temp_dir, session_state={"project_root": temp_dir})
    await MemoryWriteTool().execute({
        "name": "container", "description": "容器概念", "content": "轻量隔离", "type": "reference",
    }, ctx)
    await MemoryWriteTool().execute({
        "name": "pod", "description": "pod概念", "content": "contains [[container]]", "type": "reference",
    }, ctx)

    res = await MemoryReadTool().execute({"name": "pod"}, ctx)
    assert not res.is_error
    assert "container: 容器概念" in res.content  # wiki-link resolved inline


# ── Worktree tools ───────────────────────────────────────


@pytest.mark.asyncio
async def test_worktree_requires_git(temp_dir):
    """Non-git dir should refuse EnterWorktree."""
    from mai_agent.tools.worktree_tools import EnterWorktreeTool
    from mai_agent.tools.base import RunContext

    ctx = RunContext(cwd=temp_dir, session_state={})
    tool = EnterWorktreeTool()
    result = await tool.execute({"name": "wt1"}, ctx)
    assert result.is_error
    assert "git" in result.content.lower()


@pytest.mark.asyncio
async def test_worktree_lifecycle(temp_dir):
    """Full worktree lifecycle in a real git repo."""
    import subprocess
    from mai_agent.tools.worktree_tools import (
        EnterWorktreeTool, ExitWorktreeTool, ListWorktreesTool,
    )
    from mai_agent.tools.base import RunContext

    # Init a git repo
    subprocess.run(["git", "init", "-q"], cwd=temp_dir, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=temp_dir, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=temp_dir, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=temp_dir, check=True)
    with open(f"{temp_dir}/f.txt", "w") as f:
        f.write("hello")
    subprocess.run(["git", "add", "-A"], cwd=temp_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=temp_dir, check=True)

    original_cwd = temp_dir
    ctx = RunContext(cwd=temp_dir, session_state={})

    # Enter
    enter = EnterWorktreeTool()
    res = await enter.execute({"name": "expr1", "base_ref": "head"}, ctx)
    assert not res.is_error, res.content
    assert ctx.cwd != original_cwd
    assert "expr1" in ctx.cwd
    assert "worktrees" in ctx.cwd
    # worktree is a real git worktree
    assert os.path.isdir(ctx.cwd)

    # List should show 2 worktrees
    lst = ListWorktreesTool()
    res_list = await lst.execute({}, ctx)
    assert "expr1" in res_list.content or "mai" in res_list.content

    # Exit keeping
    exit_tool = ExitWorktreeTool()
    res_exit = await exit_tool.execute({"action": "keep"}, ctx)
    assert not res_exit.is_error
    assert ctx.cwd == original_cwd

    # Enter again then remove
    await enter.execute({"name": "expr2", "base_ref": "head"}, ctx)
    wt2 = ctx.cwd
    res_rm = await exit_tool.execute({"action": "remove"}, ctx)
    assert not res_rm.is_error, res_rm.content
    assert ctx.cwd == original_cwd
    assert not os.path.isdir(wt2)
