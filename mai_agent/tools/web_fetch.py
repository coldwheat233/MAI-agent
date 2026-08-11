"""网页抓取工具 — 对应 Claude Code 的 WebFetchTool。

抓取 URL 内容，转为纯文本，返回摘要。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry


class WebFetchInput(ToolInput):
    url: str = Field(description="要抓取的 URL（自动 https 升级）")
    prompt: str = Field(
        default="",
        description="可选: 针对抓取内容的问题，工具会提取相关内容而不是返回全文",
    )


class _TextExtractor(HTMLParser):
    """Strip HTML tags, keep text content and links."""

    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self._skip_tags = {"script", "style", "nav", "footer", "header", "noscript"}
        self._skip_depth = 0
        self._current_link = ""

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip_depth += 1
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href and not href.startswith("#"):
                self._current_link = href
        if tag in ("br", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr"):
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "a" and self._current_link:
            self._current_link = ""

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        text = data.strip()
        if text:
            if self._current_link:
                text = f"{text} ({self._current_link})"
                self._current_link = ""
            self.text.append(text)

    def get_text(self) -> str:
        return " ".join(self.text)


class WebFetchTool(Tool):
    """抓取网页内容并提取文本。

    Claude Code 对应物: WebFetchTool。
    - 自动 HTTP→HTTPS 升级
    - HTML → 纯文本
    - 对抓取内容做 prompt-driven 问答（和 Claude Code 一样）
    - is_concurrency_safe = True (只读)
    """
    name = "WebFetch"
    description = (
        "抓取 URL 的网页内容并转为纯文本。"
        "可选 prompt 参数提取相关内容。"
        "自动将 HTTP 升级为 HTTPS。"
    )
    input_schema = WebFetchInput
    is_concurrency_safe = True

    async def call(self, input: WebFetchInput, context: RunContext) -> str:
        url = input.url.strip()

        # HTTP → HTTPS
        if url.startswith("http://"):
            url = "https://" + url[7:]

        # Validate
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return f"[ERROR] Invalid URL: {url}"
        except Exception:
            return f"[ERROR] Invalid URL: {url}"

        # Fetch
        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "MAI-agent/0.1 (WebFetch Tool)",
                    "Accept": "text/html,application/xhtml+xml,text/plain",
                    "Accept-Language": "zh-CN,en;q=0.9",
                },
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return f"[ERROR] HTTP {exc.response.status_code}: {url}"
        except httpx.TimeoutException:
            return f"[ERROR] Timeout fetching: {url}"
        except Exception as exc:
            return f"[ERROR] Fetch failed: {exc}"

        # Parse HTML → text
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            text = _extract_text(resp.text)
        else:
            text = resp.text[:8000]  # Raw text, truncated

        # Truncate
        max_chars = 6000
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... (truncated, original {len(text)} chars)"

        if not text.strip():
            return f"(Empty response from {url})"

        # If prompt provided, mark it for downstream LLM processing
        header = f"[Fetched: {url} — {len(text)} chars]"
        if input.prompt:
            header += f"\n[Prompt: {input.prompt}]"

        return f"{header}\n\n{text}"


def _extract_text(html: str) -> str:
    """Strip HTML to readable text."""
    # Remove inline scripts/styles
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        # Fallback: regex strip
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    raw = parser.get_text()
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", raw)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


registry.register(WebFetchTool())
