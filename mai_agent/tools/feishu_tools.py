"""Feishu/Lark knowledge base tools.

FeishuSearch — search wiki/docs
FeishuRead   — read a document by token/url
FeishuWrite  — create or append to a document
FeishuList   — list recent documents
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


class FeishuSearchTool(Tool):
    name = "FeishuSearch"
    description = "Search your Feishu knowledge base (wiki, docs). Returns titles, URLs, and doc tokens."
    input_schema = FeishuSearchInput
    is_concurrency_safe = True

    async def call(self, input: FeishuSearchInput, context: RunContext) -> str:
        err = _check_config()
        if err:
            return f"[ERROR] {err}"

        try:
            client = _get_client()
            results = await client.search_kb(input.query)
            if not results:
                return f"No results for '{input.query}'."
            lines = [f"Search: '{input.query}'"]
            for i, r in enumerate(results, 1):
                t = r.get("title", "untitled")
                u = r.get("url", "")
                dt = r.get("doc_token", "")
                lines.append(f"  {i}. {t}")
                if u:
                    lines.append(f"     url: {u}")
                if dt:
                    lines.append(f"     doc_token: {dt}")
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
    description = ("List all documents inside a Feishu knowledge base space (知识库内文档列表). "
                   "Returns titles + doc tokens — use doc token with FeishuRead to read content.")
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
            lines = [f"Documents in space {input.space_id} ({len(docs)}):"]
            for i, d in enumerate(docs, 1):
                title = d.get("title", "untitled")
                obj_type = d.get("obj_type", "")
                token = d.get("obj_token", "")
                depth = d.get("depth", 0)
                indent = "  " * depth
                lines.append(f"  {indent}{i}. [{obj_type}] {title}")
                if token:
                    lines.append(f"     {indent}doc_token: {token}")
            return "\n".join(lines)
        except Exception as exc:
            return f"[ERROR] FeishuListSpaceDocs failed: {exc}"


registry.register(FeishuListSpaceDocsTool())


# ── Helpers ──────────────────────────────────────────────


def _extract_token(url: str) -> str:
    """Extract doc token from Feishu URL like /docx/TOKEN or /wiki/TOKEN"""
    m = re.search(r"/(docx|wiki|docs)/([A-Za-z0-9_-]+)", url)
    return m.group(2) if m else ""
