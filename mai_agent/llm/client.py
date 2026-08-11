"""LLM 客户端 — OpenAI 兼容协议。

独立的底层模块，不依赖 core/ 和 tools/，避免循环导入。

v2: 指数退避重试 + token usage 追踪。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import (
    APIError,
    APIConnectionError,
    RateLimitError,
    APIStatusError,
    AsyncOpenAI,
)

logger = logging.getLogger(__name__)

# ── 重试配置 ──────────────────────────────────────────────

MAX_RETRIES = 3
BASE_DELAY = 1.0        # 秒，指数退避起点
MAX_DELAY = 30.0        # 秒，退避上限

# HTTP 状态码分类: 可重试（短暂性故障）vs 不可重试（永久性错误）
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS = {400, 401, 402, 403, 404, 422}


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否值得重试。

    - 429 / 5xx → 是（短暂性）
    - 4xx（非 429）→ 否（请求本身有问题）
    - 连接错误 / 超时 → 是
    """
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in RETRYABLE_STATUS
    # 网络层异常（连接重置、DNS 等）
    if isinstance(exc, (ConnectionError, TimeoutError, asyncio.TimeoutError)):
        return True
    # openai 的 APIError 基类也捕获
    if isinstance(exc, APIError):
        # 无法确定状态码 → 保守：重试一次，还不行的后立刻抛出
        return True
    return False


def _retry_delay(attempt: int) -> float:
    """第 attempt 次重试（从 1 开始）的等待秒数，带 jitter。"""
    import random
    d = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
    return d + random.uniform(0, d * 0.3)  # +0~30% jitter


# ── 数据类型 ──────────────────────────────────────────────


@dataclass
class ToolCall:
    """LLM 返回的单个 tool call。"""
    id: str
    type: str = "function"
    function: "FunctionCall | None" = None


@dataclass
class FunctionCall:
    name: str
    arguments: str  # JSON string


@dataclass
class Usage:
    """单次 LLM 调用的 token 使用量。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM 单次调用返回结构。"""
    content: str | None
    tool_calls: list[ToolCall] | None
    finish_reason: str
    usage: Usage | None = None  # 新增: token 用量


# ── 客户端 ────────────────────────────────────────────────


class LLMClient:
    """轻量 LLM 客户端 — OpenAI 兼容协议，带指数退避重试。

    对应 Claude Code: services/api/ 中的 API 调用逻辑。
    作为底层模块，不依赖 tools/ 或 core/。

    重试策略:
      - 最多 3 次，指数退避 (1s → 2s → 4s)
      - 可重试: 429, 5xx, 连接错误
      - 不重试: 400, 401, 403 (直接 throw)
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-v4-pro",
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    # ── 非流式调用 ─────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """单次非流式调用（带重试）。"""
        return await _retry_loop(lambda: self._chat_impl(
            messages, tools, temperature, max_tokens,
        ), context=f"chat({len(messages)} msgs)")

    async def _chat_impl(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    function=FunctionCall(
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                    ),
                )
                for tc in msg.tool_calls
            ]

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=_extract_usage(response),
        )

    # ── 流式调用 ───────────────────────────────────────────

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        """Streaming chat completion（带重试）。

        重试时会从头开始重新发起 stream。
        本方法是一个普通 async generator——重试逻辑包装了内部实现。
        """
        # 流式重试需要特殊处理：整个生成器生命周期内只重试一次内部 stream 创建。
        # 如果在迭代过程中异常，外部 loop.py 的 async for 会捕获。
        # 这里我们把重试放在 stream 创建阶段（最常见的失败点），
        # 迭代过程中的错误由 loop.py 的 try/except 兜底。
        stream = await _retry_loop(
            lambda: self.client.chat.completions.create(**self._stream_kwargs(
                messages, tools, temperature, max_tokens,
            )),
            context=f"chat_stream({len(messages)} msgs)",
        )

        content_parts: list[str] = []
        tool_call_acc: dict[int, dict] = {}
        finish_reason: str | None = None
        final_usage: Usage | None = None

        try:
            async for chunk in stream:
                if not chunk.choices:
                    # 最终 chunk 可能只有 usage 无 choices
                    if hasattr(chunk, "usage") and chunk.usage:
                        final_usage = Usage(
                            prompt_tokens=chunk.usage.prompt_tokens or 0,
                            completion_tokens=chunk.usage.completion_tokens or 0,
                            total_tokens=chunk.usage.total_tokens or 0,
                        )
                    continue
                delta = chunk.choices[0].delta

                if delta.content:
                    content_parts.append(delta.content)
                    yield (delta.content, None, None)

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_call_acc:
                            tool_call_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_call_acc[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_call_acc[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_call_acc[idx]["arguments"] += tc_delta.function.arguments

                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
        except Exception:
            # 流迭代过程中的错误 → 让上层处理
            # 这里不加重试是因为可能已经消费了部分内容
            raise

        # Build final tool calls
        final_tool_calls = None
        if tool_call_acc:
            final_tool_calls = []
            for idx in sorted(tool_call_acc.keys()):
                tc = tool_call_acc[idx]
                final_tool_calls.append(ToolCall(
                    id=tc["id"],
                    function=FunctionCall(name=tc["name"], arguments=tc["arguments"]),
                ))

        # Yield final signal（含 usage）
        content = "".join(content_parts) if content_parts else None
        yield (None, final_tool_calls, finish_reason or "stop", final_usage)

    def _stream_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return kwargs


# ── 重试核心 ──────────────────────────────────────────────


async def _retry_loop(fn, context: str = "") -> Any:
    """执行 fn()，失败时指数退避重试。

    Raises:
        最后一次尝试的异常（如果所有重试都失败）。
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):  # 1 initial + N retries
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            if attempt > MAX_RETRIES:  # 已耗尽所有重试
                break
            if not _is_retryable(exc):
                raise  # 永久性错误，不重试

            delay = _retry_delay(attempt)
            logger.warning(
                "LLM 调用失败 (attempt %d/%d, %s): %s — %.1fs 后重试",
                attempt, MAX_RETRIES + 1, context, exc, delay,
            )
            await asyncio.sleep(delay)

    # 超过最大重试次数
    logger.error("LLM 调用所有重试均失败 (%s): %s", context, last_exc)
    raise last_exc  # type: ignore[misc]


# ── Usage 提取 ────────────────────────────────────────────


def _extract_usage(response: Any) -> Usage | None:
    """从 OpenAI/DeepSeek 响应中提取 usage。"""
    if hasattr(response, "usage") and response.usage:
        return Usage(
            prompt_tokens=response.usage.prompt_tokens or 0,
            completion_tokens=response.usage.completion_tokens or 0,
            total_tokens=response.usage.total_tokens or 0,
        )
    return None
