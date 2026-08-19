"""Feishu/Lark API client — tenant token auth, wiki docs, search.

API docs: https://open.feishu.cn/document
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://open.feishu.cn/open-apis"


class FeishuClient:
    """Minimal Feishu client — get token, search docs, read/write docs."""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: Optional[str] = None
        self._token_expires: float = 0.0
        self._http = httpx.AsyncClient(timeout=20.0)

    async def _ensure_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        resp = await self._http.post(
            f"{BASE_URL}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {data.get('msg')}")
        self._token = data["tenant_access_token"]
        self._token_expires = time.monotonic() + data.get("expire", 3600) - 60
        return self._token

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        token = await self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        resp = await self._http.request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu API error: {data.get('msg')}")
        return data.get("data", data)

    # ── Wiki / Knowledge Base ──────────────────────────

    async def list_spaces(self, page_size: int = 50) -> list[dict]:
        """列出当前应用可访问的所有知识库空间（wiki spaces）。

        返回: [{space_id, name, description, space_type, visibility}]
        """
        result = await self._request("GET", "/wiki/v2/spaces", params={"page_size": page_size})
        items = result.get("items", [])
        spaces = []
        for s in items:
            spaces.append({
                "space_id": s.get("space_id", ""),
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "space_type": s.get("space_type", ""),
                "visibility": s.get("visibility", ""),
            })
        return spaces

    async def list_space_docs(self, space_id: str, page_size: int = 100,
                              max_depth: int = 5) -> list[dict]:
        """列出知识库空间内的全部文档节点（递归遍历节点树）。

        返回: [{title, node_token, obj_token, obj_type, parent_node_token, depth}]
        """
        results: list[dict] = []

        async def _walk(parent_token: str = "", depth: int = 0):
            if len(results) >= page_size or depth > max_depth:
                return
            try:
                nodes = await self._request(
                    "GET", f"/wiki/v2/spaces/{space_id}/nodes",
                    params={"page_size": 50, "parent_node_token": parent_token},
                )
            except Exception:
                return
            for n in nodes.get("items", []):
                if len(results) >= page_size:
                    return
                results.append({
                    "title": n.get("title", ""),
                    "node_token": n.get("node_token", ""),
                    "obj_token": n.get("obj_token", ""),
                    "obj_type": n.get("obj_type", ""),
                    "parent_node_token": n.get("parent_node_token", ""),
                    "depth": depth,
                })
                if n.get("has_child", False):
                    await _walk(n.get("node_token", ""), depth + 1)

        await _walk()
        return results[:page_size]

    async def search_kb(self, query: str, page_size: int = 10) -> list[dict]:
        """Search Feishu knowledge base by traversing node tree.

        Feishu 没有 wiki 级别的全文搜索 API（/wiki/v2/search 不存在）。
        通过遍历空间节点树，按标题做子串匹配来实现搜索。
        """
        results: list[dict] = []
        query_lower = query.lower()

        # 1. 列出所有可访问的知识库空间
        spaces = await self._request("GET", "/wiki/v2/spaces", params={"page_size": 50})
        space_items = spaces.get("items", [])

        # 2. 递归遍历每个空间的节点树
        async def _walk_nodes(space_id: str, parent_token: str = "", depth: int = 0):
            if len(results) >= page_size:
                return
            try:
                nodes = await self._request(
                    "GET", f"/wiki/v2/spaces/{space_id}/nodes",
                    params={"page_size": 50, "parent_node_token": parent_token},
                )
            except Exception:
                return
            for n in nodes.get("items", []):
                if len(results) >= page_size:
                    return
                title = n.get("title", "")
                obj_token = n.get("obj_token", "")
                obj_type = n.get("obj_type", "")
                node_token = n.get("node_token", "")
                has_child = n.get("has_child", False)

                # 标题子串匹配（不区分大小写）
                if query_lower in title.lower():
                    results.append({
                        "title": title,
                        "doc_token": obj_token,
                        "obj_type": obj_type,
                        "url": f"https://bytedance.feishu.cn/{obj_type}/{obj_token}",
                        "space_id": space_id,
                        "node_token": node_token,
                    })

                # 递归子节点（限制深度避免超时）
                if has_child and depth < 5:
                    await _walk_nodes(space_id, node_token, depth + 1)

        for space in space_items:
            await _walk_nodes(space.get("space_id", ""))
            if len(results) >= page_size:
                break

        return results[:page_size]

    async def read_doc(self, doc_token: str) -> str:
        """Read raw content of a Feishu document."""
        result = await self._request("GET", f"/docx/v1/documents/{doc_token}/raw_content")
        content = result.get("content", "")
        # content is JSON string of blocks
        try:
            blocks = json.loads(content) if isinstance(content, str) else content
            return _blocks_to_text(blocks)
        except Exception:
            return content[:5000] if isinstance(content, str) else str(content)[:5000]

    async def create_doc(self, title: str, content: str, folder_token: str = "",
                         space_id: str = "", parent_node_token: str = "") -> str:
        """Create a Feishu document, optionally linked to a knowledge base space.
        
        If space_id and parent_node_token are provided, the doc is also added as
        a wiki node under the given parent.
        
        Returns doc_token (obj_token if linked to wiki, else document_id).
        """
        result = await self._request(
            "POST", "/docx/v1/documents",
            json={
                "title": title,
                "folder_token": folder_token,
            },
        )
        doc_id = result.get("document", {}).get("document_id", "")

        # Write content
        if doc_id and content:
            await self._write_content(doc_id, content)

        # Move the doc into the knowledge base if space_id provided.
        # NOTE: creating a wiki node via POST /wiki/v2/spaces/{space_id}/nodes
        # creates a NEW blank doc (ignoring obj_token), so we must use the
        # move_docs_to_wiki endpoint to attach the already-written doc.
        if doc_id and space_id:
            await self._request(
                "POST", f"/wiki/v2/spaces/{space_id}/nodes/move_docs_to_wiki",
                json={
                    "obj_type": "docx",
                    "obj_token": doc_id,
                    "parent_wiki_token": parent_node_token,
                    "apply": True,
                },
            )
            # After move, the doc keeps the same document_id as its wiki obj_token.
            return doc_id

        return doc_id

    async def _write_content(self, doc_token: str, content: str) -> None:
        """Write markdown content to a document (batched to avoid API limits)."""
        blocks = _markdown_to_blocks(content)
        batch_size = 50
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i:i + batch_size]
            await self._request(
                "POST", f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
                json={"children": batch},
            )

    async def append_doc(self, doc_token: str, content: str) -> None:
        """Append content to an existing document."""
        await self._write_content(doc_token, content)

    async def list_recent(self, page_size: int = 20) -> list[dict]:
        """List recently accessed documents."""
        result = await self._request(
            "GET", "/drive/v1/files",
            params={"page_size": page_size, "order_by": "EditedTime", "direction": "DESC"},
        )
        files = result.get("files", [])
        return [{
            "name": f.get("name", ""),
            "token": f.get("token", ""),
            "type": f.get("type", ""),
            "url": f.get("url", ""),
        } for f in files]

    async def close(self):
        await self._http.aclose()


# ── Text ↔ Feishu blocks ────────────────────────────────


def _blocks_to_text(blocks: list) -> str:
    """Convert Feishu block tree to plain text."""
    TEXT_TYPES = ("text", "heading1", "heading2", "heading3", "bullet", "ordered", "code")
    lines: list[str] = []
    for b in blocks:
        t = None
        for key in TEXT_TYPES:
            if key in b:
                t = b[key]
                break
        if t is None:
            continue
        if isinstance(t, dict):
            elements = t.get("elements", [])
            for e in elements:
                if e.get("text_run"):
                    lines.append(e["text_run"].get("content", ""))
        elif isinstance(t, str):
            lines.append(t)
    return "\n".join(lines)


def _text_to_blocks(text: str) -> list[dict]:
    """Convert plain text lines to Feishu block format (simple fallback)."""
    blocks = []
    for line in text.splitlines():
        if not line.strip():
            continue
        blocks.append({
            "block_type": 2,  # text
            "text": {
                "elements": [{"text_run": {"content": line}}],
                "style": {},
            },
        })
    return blocks


# ── Markdown → Feishu blocks ──────────────────────────────
#
# Feishu docx block_type 映射（关键枚举）:
#   2  text      3-11 heading1-9   12 bullet    13 ordered
#   14 code      15 quote          22 divider
#
# 文本内联样式 (text_element_style): bold / italic / inline_code / link

_INLINE_RE = re.compile(
    r"(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\n]+\))"
)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _parse_inline(text: str) -> list[dict]:
    """Parse inline markdown (bold / italic / inline code / links) into text_run elements."""
    elements: list[dict] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            elements.append(_text_run(text[pos:m.start()]))
        token = m.group(0)
        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            elements.append(_text_run(token[2:-2], bold=True))
        elif token.startswith("*") and token.endswith("*") and len(token) > 2:
            elements.append(_text_run(token[1:-1], italic=True))
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            elements.append(_text_run(token[1:-1], inline_code=True))
        else:
            lm = _LINK_RE.match(token)
            if lm:
                elements.append(_text_run(lm.group(1), link=lm.group(2)))
            else:
                elements.append(_text_run(token))
        pos = m.end()
    if pos < len(text):
        elements.append(_text_run(text[pos:]))
    return elements


def _text_run(content: str, bold: bool = False, italic: bool = False,
              inline_code: bool = False, link: str = "") -> dict:
    """Build a single Feishu text_run element."""
    style: dict[str, Any] = {}
    if bold:
        style["bold"] = True
    if italic:
        style["italic"] = True
    if inline_code:
        style["inline_code"] = True
    if link:
        style["link"] = {"url": link}
    return {"text_run": {"content": content, "text_element_style": style}}


def _rich_block(field: str, block_type: int, text: str) -> dict:
    """Build a block that carries a single inline-rich text field."""
    return {
        "block_type": block_type,
        field: {"elements": _parse_inline(text), "style": {}},
    }


def _markdown_to_blocks(md: str) -> list[dict]:
    """Convert markdown text to a Feishu block tree.

    Supports:
      - headings (# → ######)
      - bullet lists (- / * / +)
      - ordered lists (1. / 1))
      - blockquotes (>)
      - fenced code blocks (```)
      - horizontal rules (--- / ***)
      - inline bold / italic / inline code / links
    """
    blocks: list[dict] = []
    lines = md.splitlines()
    i, n = 0, len(lines)
    in_code = False
    code_lines: list[str] = []

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            if in_code:
                blocks.append(_code_block("\n".join(code_lines)))
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue

        # Blank line
        if not stripped:
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            blocks.append({"block_type": 22, "divider": {}})
            i += 1
            continue

        # Heading (# → ######)
        hm = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if hm:
            level = len(hm.group(1))
            blocks.append(_rich_block(f"heading{level}", 2 + level, hm.group(2)))
            i += 1
            continue

        # Bullet list
        bm = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bm:
            blocks.append(_rich_block("bullet", 12, bm.group(1)))
            i += 1
            continue

        # Ordered list
        om = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if om:
            blocks.append(_rich_block("ordered", 13, om.group(2)))
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            blocks.append(_rich_block("quote", 15, stripped.lstrip(">").strip()))
            i += 1
            continue

        # Normal paragraph
        blocks.append(_rich_block("text", 2, stripped))
        i += 1

    # Unclosed code block
    if in_code and code_lines:
        blocks.append(_code_block("\n".join(code_lines)))

    return blocks


def _code_block(code: str) -> dict:
    """Build a Feishu code block (block_type 14)."""
    return {
        "block_type": 14,
        "code": {
            "elements": [{"text_run": {"content": code, "text_element_style": {}}}],
            "style": {},
        },
    }
