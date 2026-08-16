"""记忆工具 — 标签化长期记忆卡片的增删查。

对应 Claude Code 的记忆操作能力：写入/检索/列表标签化记忆卡片，
建立 [[name]] wiki-link 关联。与会话自动摘要（SESSION_MEMORY.md）互补：
  - 自动摘要 = 时间线流水
  - 标签卡片 = 可检索的知识网
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry
from mai_agent.services import memory_tags


def _root(context: RunContext) -> str:
    return context.session_state.get("project_root", context.cwd)


# ── MemoryWrite ───────────────────────────────────────────


class MemoryWriteInput(ToolInput):
    name: str = Field(description="记忆唯一标识（kebab-case，如 distributed-lock）")
    description: str = Field(description="一句话摘要（用于索引行）")
    content: str = Field(description="记忆正文（Markdown，可用 [[other]] 关联其他记忆）")
    type: str = Field(
        default="reference",
        description="类型: user(用户画像) | feedback(工作反馈) | project(项目) | reference(参考资料)",
    )
    tags: Optional[list[str]] = Field(
        default=None, description="标签列表，用于分类检索",
    )


class MemoryWriteTool(Tool):
    """创建或更新一条标签化长期记忆卡片。"""
    name = "MemoryWrite"
    description = (
        "保存一条长期记忆卡片到 .mai/memory/。带 name/description/type/tags，"
        "正文可用 [[name]] wiki-link 关联其他记忆。用于沉淀跨会话的持久知识。"
    )
    input_schema = MemoryWriteInput
    is_concurrency_safe = False

    async def call(self, input: MemoryWriteInput, context: RunContext) -> str:
        root = _root(context)
        existing = memory_tags.load_memory_by_name(input.name, root)
        mem = memory_tags.TaggedMemory(
            name=input.name,
            description=input.description,
            type=input.type,
            tags=input.tags or (existing.tags if existing else []),
            content=input.content,
            created_at=(existing.created_at if existing else ""),
        )
        path = memory_tags.save_memory(mem, root)
        action = "更新" if existing else "创建"
        return (
            f"已{action}记忆卡片: {input.name}\n"
            f"  路径: {path}\n"
            f"  类型: {mem.type}\n"
            f"  标签: {', '.join(mem.tags) or '(无)'}"
        )


registry.register(MemoryWriteTool())


# ── MemorySearch ──────────────────────────────────────────


class MemorySearchInput(ToolInput):
    query: Optional[str] = Field(default=None, description="全文检索关键词")
    tag: Optional[str] = Field(default=None, description="按标签精确检索")
    type: Optional[str] = Field(default=None, description="按类型检索: user|feedback|project|reference")
    start: Optional[str] = Field(default=None, description="起始日期（YYYY-MM-DD，含）")
    end: Optional[str] = Field(default=None, description="结束日期（YYYY-MM-DD，含）")


class MemorySearchTool(Tool):
    """检索长期记忆卡片：按全文/标签/类型。"""
    name = "MemorySearch"
    description = "检索 .mai/memory/ 中的长期记忆卡片。可按关键词全文检索、按标签或按类型过滤。"
    input_schema = MemorySearchInput
    is_concurrency_safe = True

    async def call(self, input: MemorySearchInput, context: RunContext) -> str:
        root = _root(context)

        if input.start or input.end:
            results = memory_tags.search_by_daterange(
                input.start, input.end, input.tag, root)
        elif input.tag:
            results = memory_tags.search_by_tag(input.tag, root)
        elif input.type:
            results = memory_tags.search_by_type(input.type, root)
        elif input.query:
            results = memory_tags.search(input.query, root)
        else:
            results = memory_tags.load_all_memories(root)

        if not results:
            return "未找到匹配的记忆卡片。"

        lines = [f"找到 {len(results)} 条记忆:"]
        for m in sorted(results, key=lambda x: x.name):
            tags = f" [{', '.join(m.tags)}]" if m.tags else ""
            links = m.wiki_links()
            link_str = f" -> {', '.join('[['+l+']]' for l in links)}" if links else ""
            lines.append(f"- [[{m.name}]] ({m.type}){tags} — {m.description}{link_str}")
        return "\n".join(lines)


registry.register(MemorySearchTool())


# ── MemoryRead ────────────────────────────────────────────


class MemoryReadInput(ToolInput):
    name: str = Field(description="记忆卡片名称")
    resolve_links: bool = Field(
        default=True,
        description="是否内联解析 [[wiki-link]] 为对应摘要",
    )


class MemoryReadTool(Tool):
    """读取单条记忆卡片全文，可选解析 wiki-link 关联。"""
    name = "MemoryRead"
    description = "按名读取一条长期记忆卡片的完整内容。可选内联解析 [[wiki-link]] 关联。"
    input_schema = MemoryReadInput
    is_concurrency_safe = True

    async def call(self, input: MemoryReadInput, context: RunContext) -> str:
        root = _root(context)
        m = memory_tags.load_memory_by_name(input.name, root)
        if m is None:
            return f"[ERROR] 记忆不存在: {input.name}"

        content = m.content
        if input.resolve_links:
            content = memory_tags.resolve_wikilinks(content, root)

        related = memory_tags.related_memories(input.name, root)
        related_str = ""
        if related:
            related_str = "\n\n[关联记忆]\n" + "\n".join(
                f"- [[{r.name}]] — {r.description}" for r in related
            )

        return (
            f"[{m.name}] ({m.type})\n"
            f"描述: {m.description}\n"
            f"标签: {', '.join(m.tags) or '(无)'}\n\n"
            f"{content}{related_str}"
        )


registry.register(MemoryReadTool())


# ── MemoryList ────────────────────────────────────────────


class MemoryListInput(ToolInput):
    pass


class MemoryListTool(Tool):
    """列出所有长期记忆卡片索引 + 所有标签。"""
    name = "MemoryList"
    description = "列出 .mai/memory/ 全部记忆卡片索引与可用标签。"
    input_schema = MemoryListInput
    is_concurrency_safe = True

    async def call(self, input: MemoryListInput, context: RunContext) -> str:
        root = _root(context)
        memories = memory_tags.load_all_memories(root)
        tags = memory_tags.all_tags(root)
        if not memories:
            return "尚无长期记忆卡片。用 MemoryWrite 创建。"
        lines = [f"共 {len(memories)} 条记忆:"]
        for m in sorted(memories, key=lambda x: x.name):
            tag_str = f" [{', '.join(m.tags)}]" if m.tags else ""
            lines.append(f"- [[{m.name}]] ({m.type}){tag_str} — {m.description}")
        if tags:
            lines.append(f"\n可用标签: {', '.join(tags)}")
        return "\n".join(lines)


registry.register(MemoryListTool())


# ── MemoryDelete ──────────────────────────────────────────


class MemoryDeleteInput(ToolInput):
    name: str = Field(description="要删除的记忆卡片名称")


class MemoryDeleteTool(Tool):
    """删除一条长期记忆卡片。"""
    name = "MemoryDelete"
    description = "按名删除一条长期记忆卡片（同时刷新索引）。"
    input_schema = MemoryDeleteInput
    is_concurrency_safe = False

    async def call(self, input: MemoryDeleteInput, context: RunContext) -> str:
        root = _root(context)
        if memory_tags.delete_memory(input.name, root):
            return f"已删除记忆卡片: {input.name}"
        return f"[ERROR] 记忆不存在: {input.name}"


registry.register(MemoryDeleteTool())
