"""网页搜索工具 — 对应 Claude Code 的 WebSearchTool。

搜索源回退链（按优先级，国内网络环境适配）:
  1. Tavily API  — TAVILY_API_KEY 存在时启用，质量最好（专为 AI agent 设计）
  2. Bing HTML   — cn.bing.com，无需 Key，国内直连可用
  3. DuckDuckGo  — Instant Answer API，海外网络兜底（国内被墙，超时空转）

背景：原实现只接 DuckDuckGo，国内无代理必超时——且 DDG Instant Answer
本身只回答"直接答案类"查询，通用搜索质量差。三层回退保证任一可用源即返回。
"""

from __future__ import annotations

import html
import json
import os
import re
from typing import Any

import httpx
from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = 12.0


class WebSearchInput(ToolInput):
    query: str = Field(description="搜索关键词")
    allowed_domains: list[str] = Field(default_factory=list, description="限定搜索域名")


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _filter_domains(results: list[dict[str, str]], domains: list[str]) -> list[dict[str, str]]:
    if not domains:
        return results
    return [r for r in results if any(d in r.get("url", "") for d in domains)]


async def _search_tavily(query: str) -> list[dict[str, str]]:
    """Tavily API（需 TAVILY_API_KEY）。"""
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no key")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": 10},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in data.get("results", [])
    ]


async def _search_bing(query: str) -> list[dict[str, str]]:
    """Bing HTML 搜索（cn.bing.com，无需 Key）。

    解析 <li class="b_algo"> 结果块：<h2><a> 出标题+URL，<p> 出摘要。
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(
            "https://cn.bing.com/search",
            params={"q": query, "count": "15"},
            headers=_UA,
        )
        resp.raise_for_status()
        page = resp.text

    results: list[dict[str, str]] = []
    for m in re.finditer(
        r'<li class="b_algo".*?<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>(.*?)</li>',
        page, re.DOTALL,
    ):
        url, title_html, body = m.group(1), m.group(2), m.group(3)
        p = re.search(r"<p[^>]*>(.*?)</p>", body, re.DOTALL)
        results.append({
            "title": _strip_tags(title_html),
            "url": html.unescape(url),
            "snippet": _strip_tags(p.group(1)) if p else "",
        })
        if len(results) >= 10:
            break
    return results


async def _search_duckduckgo(query: str) -> list[dict[str, str]]:
    """DuckDuckGo Instant Answer API（免费，无需Key；国内不可达，作兜底）。"""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
        )
        data = resp.json()

    results: list[dict[str, str]] = []
    if data.get("AbstractText"):
        results.append({
            "title": data.get("AbstractSource", "DuckDuckGo"),
            "url": data.get("AbstractURL", ""),
            "snippet": data["AbstractText"],
        })
    for topic in data.get("RelatedTopics", [])[:5]:
        if isinstance(topic, dict) and topic.get("Text"):
            results.append({
                "title": topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                "url": topic.get("FirstURL", ""),
                "snippet": topic["Text"],
            })
    return results


class WebSearchTool(Tool):
    """网页搜索（Tavily → Bing → DuckDuckGo 三层回退）"""
    name = "WebSearch"
    description = "搜索网页并返回结果（标题+URL+摘要）"
    input_schema = WebSearchInput
    is_concurrency_safe = True

    async def call(self, input: WebSearchInput, context: RunContext) -> str:
        query = input.query.strip()
        if not query:
            return "[ERROR] 搜索关键词不能为空"

        # 按优先级依次尝试，记录各源失败原因便于诊断
        providers = [
            ("tavily", _search_tavily),
            ("bing", _search_bing),
            ("duckduckgo", _search_duckduckgo),
        ]
        errors: list[str] = []
        results: list[dict[str, str]] = []
        used = ""
        for name, fn in providers:
            try:
                results = await fn(query)
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__} {exc}")
                continue
            if results:
                used = name
                break
            errors.append(f"{name}: 0 results")

        if not results:
            return (
                f"[ERROR] 搜索 '{query}' 失败：所有搜索源均无结果或不可达。"
                f"明细: {'; '.join(errors) or '无'}。"
                "提示：国内网络下 DuckDuckGo 被墙属预期，Bing 应可用；"
                "配置 TAVILY_API_KEY 可获得最稳定的搜索质量。"
            )

        results = _filter_domains(results, input.allowed_domains)
        if not results:
            return f"关于 '{query}' 在限定域名 {input.allowed_domains} 内没有找到结果。"

        lines = [f"搜索 '{query}' 的结果（via {used}）:"]
        for i, r in enumerate(results[:10], 1):
            lines.append(f"{i}. **{r['title']}**")
            lines.append(f"   {r['url']}")
            if r.get('snippet'):
                lines.append(f"   {r['snippet']}")
        return "\n".join(lines)


registry.register(WebSearchTool())
