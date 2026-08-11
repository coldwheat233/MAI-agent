"""网页搜索工具 — 对应 Claude Code 的 WebSearchTool。"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
from typing import Any

import httpx
from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry


class WebSearchInput(ToolInput):
    query: str = Field(description="搜索关键词")
    allowed_domains: list[str] = Field(default_factory=list, description="限定搜索域名")


class WebSearchTool(Tool):
    """网页搜索（DuckDuckGo 免费 API，无需 Key）"""
    name = "WebSearch"
    description = "搜索网页并返回结果（标题+URL+摘要）"
    input_schema = WebSearchInput
    is_concurrency_safe = True

    async def call(self, input: WebSearchInput, context: RunContext) -> str:
        query = input.query.strip()
        if not query:
            return "[ERROR] 搜索关键词不能为空"

        try:
            results = await self._search_duckduckgo(query)
        except Exception as exc:
            return f"[ERROR] 搜索失败: {exc}"

        if not results:
            return f"关于 '{query}' 没有找到结果。"

        lines = [f"搜索 '{query}' 的结果:"]
        for i, r in enumerate(results[:10], 1):
            lines.append(f"{i}. **{r['title']}**")
            lines.append(f"   {r['url']}")
            if r.get('snippet'):
                lines.append(f"   {r['snippet']}")
        return "\n".join(lines)

    async def _search_duckduckgo(self, query: str) -> list[dict[str, str]]:
        """使用 DuckDuckGo Instant Answer API（免费，无需Key）"""
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()

        results: list[dict[str, str]] = []

        # Abstract（直接答案）
        if data.get("AbstractText"):
            results.append({
                "title": data.get("AbstractSource", "DuckDuckGo"),
                "url": data.get("AbstractURL", ""),
                "snippet": data["AbstractText"],
            })

        # Related Topics
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic["Text"],
                })

        return results


registry.register(WebSearchTool())
