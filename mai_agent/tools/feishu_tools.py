"""Feishu/Lark knowledge base tools.

FeishuListSpaces    — 按知识库名浏览（列出可访问的知识库空间）
FeishuListSpaceDocs — 知识库目录树（列出空间下全部文档，带层级）
FeishuSearch        — 检索（title 标题 / fulltext 全文两种模式）
FeishuRead          — 读单篇文档（by token/url）
FeishuReadSpace     — 读整个知识库空间（批量读取正文）
FeishuWrite         — 创建 / 追加文档
FeishuList          — 最近访问文档
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import Field

from mai_agent.config import get_config
from mai_agent.services.feishu import FeishuClient
from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry

_client: Optional[FeishuClient] = None


def _get_client() -> FeishuClient:
    global _client
    config = get_config()
    if _client is None or _client.app_id != config.feishu_app_id:
        _client = FeishuClient(config.feishu_app_id, config.feishu_app_secret)
    return _client


def _check_config() -> Optional[str]:
    config = get_config()
    if not config.feishu_app_id or not config.feishu_app_secret:
        return "Feishu not configured. Set FEISHU_APP_ID and FEISHU_APP_SECRET in .env"
    return None


# ── FeishuSearch ──────────────────────────────────────────


class FeishuSearchInput(ToolInput):
    query: str = Field(description="Search keywords for knowledge base")
    mode: str = Field(default="title",
                      description="'title' = match doc titles only (fast); 'fulltext' = search inside doc body (slow)")
    space_id: Optional[str] = Field(default=None, description="Optional: limit search to one knowledge base space id")
    max_scan_docs: int = Field(default=300, description="Fulltext mode: max docs to scan (avoid quota burn)")
    page_size: int = Field(default=10, description="Max number of results")


class FeishuSearchTool(Tool):
    name = "FeishuSearch"
    description = ("Search your Feishu knowledge base (wiki, docs). mode='title' matches doc titles; "
                   "mode='fulltext' also searches inside document body and returns matching snippets.")
    input_schema = FeishuSearchInput
    is_concurrency_safe = True

    async def call(self, input: FeishuSearchInput, context: RunContext) -> str:
        err = _check_config()
        if err:
            return f"[ERROR] {err}"

        try:
            client = _get_client()
            results, meta = await client.search_kb(
                input.query,
                page_size=input.page_size,
                mode=input.mode,
                space_id=input.space_id or "",
                max_scan_docs=input.max_scan_docs,
            )
            if not results:
                return f"No results for '{input.query}' (mode={input.mode})."
            lines = [f"Search: '{input.query}' (mode={input.mode}, scanned_docs={meta.get('scanned_docs', 0)})"]
            for i, r in enumerate(results, 1):
                t = r.get("title", "untitled")
                u = r.get("url", "")
                dt = r.get("doc_token", "")
                hit = r.get("hit", "title")
                path = r.get("path", "")
                lines.append(f"  {i}. [{hit}] {t}")
                if path and path != t:
                    lines.append(f"     path: {path}")
                if u:
                    lines.append(f"     url: {u}")
                if dt:
                    lines.append(f"     doc_token: {dt}")
                snippet = r.get("snippet", "")
                if hit == "content" and snippet:
                    lines.append(f"     snippet: ...{snippet}...")
            return "\n".join(lines)
        except Exception as exc:
            return f"[ERROR] FeishuSearch failed: {exc}"


registry.register(FeishuSearchTool())


# ── FeishuRead ────────────────────────────────────────────


class FeishuReadInput(ToolInput):
    doc_token: str = Field(description="Document token (from search results or URL)")
    url: Optional[str] = Field(default=None, description="Alternatively, a Feishu document URL")


class FeishuReadTool(Tool):
    name = "FeishuRead"
    description = "Read the content of a Feishu document by token or URL."
    input_schema = FeishuReadInput
    is_concurrency_safe = True

    async def call(self, input: FeishuReadInput, context: RunContext) -> str:
        err = _check_config()
        if err:
            return f"[ERROR] {err}"

        token = input.doc_token
        if not token and input.url:
            token = _extract_token(input.url)
        if not token:
            return "[ERROR] doc_token is required"

        try:
            client = _get_client()
            content = await client.read_doc(token)
            if not content.strip():
                return f"(Empty document: {token})"
            return f"[Document: {token}]\n{content[:4000]}"
        except Exception as exc:
            return f"[ERROR] FeishuRead failed: {exc}"


registry.register(FeishuReadTool())


# ── FeishuWrite ───────────────────────────────────────────


class FeishuWriteInput(ToolInput):
    title: str = Field(description="Document title")
    content: str = Field(description="Document content (markdown or plain text)")
    doc_token: Optional[str] = Field(default=None, description="Optional: append to existing document instead of creating new")
    mode: str = Field(default="create", description="'create' (new doc) or 'append' (add to existing)")


class FeishuWriteTool(Tool):
    name = "FeishuWrite"
    description = "Create a new Feishu document or append content to an existing one."
    input_schema = FeishuWriteInput
    is_concurrency_safe = False

    async def call(self, input: FeishuWriteInput, context: RunContext) -> str:
        err = _check_config()
        if err:
            return f"[ERROR] {err}"

        try:
            client = _get_client()
            if input.mode == "append" and input.doc_token:
                await client.append_doc(input.doc_token, input.content)
                return f"Appended to document: {input.doc_token}"
            else:
                doc_token = await client.create_doc(input.title, input.content)
                return f"Document created: {input.title}\nURL: https://bytedance.feishu.cn/docx/{doc_token}\nToken: {doc_token}"
        except Exception as exc:
            return f"[ERROR] FeishuWrite failed: {exc}"


registry.register(FeishuWriteTool())


# ── FeishuList ────────────────────────────────────────────


class FeishuListInput(ToolInput):
    page_size: int = Field(default=20, description="Number of results")


class FeishuListTool(Tool):
    name = "FeishuList"
    description = "List recently accessed Feishu documents."
    input_schema = FeishuListInput
    is_concurrency_safe = True

    async def call(self, input: FeishuListInput, context: RunContext) -> str:
        err = _check_config()
        if err:
            return f"[ERROR] {err}"

        try:
            client = _get_client()
            files = await client.list_recent(input.page_size)
            if not files:
                return "No recent documents."
            lines = [f"Recent documents ({len(files)}):"]
            for f in files:
                name = f.get("name", "untitled")
                token = f.get("token", "")
                url = f.get("url", "")
                lines.append(f"  - {name}")
                if url:
                    lines.append(f"    {url}")
            return "\n".join(lines)
        except Exception as exc:
            return f"[ERROR] FeishuList failed: {exc}"


registry.register(FeishuListTool())


# ── FeishuListSpaces ─────────────────────────────────────
# 知识库名搜索：列出可访问的知识库空间，可按名称过滤


class FeishuListSpacesInput(ToolInput):
    query: Optional[str] = Field(default=None, description="Optional: filter spaces by name (substring, case-insensitive)")


class FeishuListSpacesTool(Tool):
    name = "FeishuListSpaces"
    description = ("List your Feishu knowledge base spaces (知识库), optionally filtered by name. "
                   "Returns space_id + name for each knowledge base — use space_id with FeishuListSpaceDocs.")
    input_schema = FeishuListSpacesInput
    is_concurrency_safe = True

    async def call(self, input: FeishuListSpacesInput, context: RunContext) -> str:
        err = _check_config()
        if err:
            return f"[ERROR] {err}"

        try:
            client = _get_client()
            spaces = await client.list_spaces()
            if input.query:
                q = input.query.lower()
                spaces = [s for s in spaces if q in s.get("name", "").lower()]
            if not spaces:
                return "No knowledge base spaces found."
            lines = [f"Knowledge base spaces ({len(spaces)}):"]
            for i, s in enumerate(spaces, 1):
                name = s.get("name", "untitled")
                desc = s.get("description", "")
                sid = s.get("space_id", "")
                lines.append(f"  {i}. {name}")
                if desc:
                    lines.append(f"     description: {desc}")
                lines.append(f"     space_id: {sid}")
            return "\n".join(lines)
        except Exception as exc:
            return f"[ERROR] FeishuListSpaces failed: {exc}"


registry.register(FeishuListSpacesTool())


# ── FeishuListSpaceDocs ──────────────────────────────────
# 读取知识库内列表：列出某个知识库空间下的全部文档


class FeishuListSpaceDocsInput(ToolInput):
    space_id: str = Field(description="Knowledge base space id (from FeishuListSpaces)")
    page_size: int = Field(default=100, description="Max number of documents to list")


class FeishuListSpaceDocsTool(Tool):
    name = "FeishuListSpaceDocs"
    description = ("List all documents inside a Feishu knowledge base space as a directory tree (知识库目录树). "
                   "Returns titles with hierarchy + doc tokens — use doc token with FeishuRead to read content.")
    input_schema = FeishuListSpaceDocsInput
    is_concurrency_safe = True

    async def call(self, input: FeishuListSpaceDocsInput, context: RunContext) -> str:
        err = _check_config()
        if err:
            return f"[ERROR] {err}"

        try:
            client = _get_client()
            docs = await client.list_space_docs(input.space_id, page_size=input.page_size)
            if not docs:
                return "No documents in this knowledge base space."
            lines = [f"Directory tree of space {input.space_id} ({len(docs)} nodes):"]
            for d in docs:
                title = d.get("title", "untitled")
                obj_type = d.get("obj_type", "")
                token = d.get("obj_token", "")
                depth = d.get("depth", 0)
                marker = "■ " if depth == 0 else "├ "
                indent = "  " * depth
                branch = f"{'  ' * depth}{marker}"
                lines.append(f"  {branch}{title} [{obj_type}]")
                if token:
                    lines.append(f"     {'  ' * depth}doc_token: {token}")
            return "\n".join(lines)
        except Exception as exc:
            return f"[ERROR] FeishuListSpaceDocs failed: {exc}"


registry.register(FeishuListSpaceDocsTool())


# ── FeishuReadSpace ─────────────────────────────────────
# 读知识库空间：一次性读取空间下所有文档正文（截断版）


class FeishuReadSpaceInput(ToolInput):
    space_id: str = Field(description="Knowledge base space id (from FeishuListSpaces)")
    max_docs: int = Field(default=15, description="Max number of docs to read (tree order)")
    per_doc_chars: int = Field(default=800, description="Chars kept per doc to limit output size")


class FeishuReadSpaceTool(Tool):
    name = "FeishuReadSpace"
    description = ("Read content of an entire Feishu knowledge base space (读知识库空间): returns body of every "
                   "docx in tree order, truncated per doc. Use FeishuRead for full single-doc content.")
    input_schema = FeishuReadSpaceInput
    is_concurrency_safe = False

    async def call(self, input: FeishuReadSpaceInput, context: RunContext) -> str:
        err = _check_config()
        if err:
            return f"[ERROR] {err}"

        try:
            client = _get_client()
            docs = await client.read_space(
                input.space_id,
                max_docs=input.max_docs,
                per_doc_chars=input.per_doc_chars,
            )
            if not docs:
                return "No readable docx documents in this space."
            lines = [f"Space content {input.space_id} ({len(docs)} docs, tree order):"]
            for d in docs:
                title = d.get("title", "untitled")
                depth = d.get("depth", 0)
                content = d.get("content", "").strip()
                lines.append(f"\n{'  ' * depth}■ {title}")
                lines.append(f"  doc_token: {d.get('obj_token', '')}")
                if content:
                    lines.append(f"  content: {content[: input.per_doc_chars]}")
                else:
                    lines.append("  (empty or unreadable)")
            return "\n".join(lines)
        except Exception as exc:
            return f"[ERROR] FeishuReadSpace failed: {exc}"


registry.register(FeishuReadSpaceTool())


# ── Helpers ──────────────────────────────────────────────


def _extract_token(url: str) -> str:
    """Extract doc token from Feishu URL like /docx/TOKEN or /wiki/TOKEN"""
    m = re.search(r"/(docx|wiki|docs)/([A-Za-z0-9_-]+)", url)
    return m.group(2) if m else ""
