"""Trace 采集服务 — span 级轨迹记录（对齐 OpenTelemetry GenAI 语义约定的轻量自研版）。

设计（无框架依赖，复用 structured_logger 的异步队列模式）：
  - 一次会话 = 一个 Trace；Trace 由多个 Span 组成
  - Span 类型:
      llm   — 一次 LLM 调用（model / input_tokens / output_tokens / cost / duration_ms / finish_reason）
      tool  — 一次工具执行（name / args / result / is_error / duration_ms）
      brain — 子 Agent 孵化（brain 类型、孵化工具）
  - 落盘: .mai/traces/{session_id}.jsonl（追加式，每行一个 span）
  - 成本估算: 按模型单价查表（DeepSeek 官方定价，USD/1K tokens）
  - 采集入口: loop.py（LLM 调用后 / 工具执行后）+ RunContext.trace 注入

为什么不用 OpenTelemetry SDK:
  - 项目风格是"理解原理后自己实现"，OTel 对单机桌面应用是重依赖
  - 只需要 jsonl 落盘 + 一个读取端点，自己实现 ~150 行
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

TRACE_DIR = ".mai/traces"
QUEUE_SIZE = 500


# ── 成本估算（DeepSeek 官方单价，USD / 1K tokens）──────────
# 参考: https://api-docs.deepseek.com/quick_start/pricing
# 命中不到模型的按最接近档位兜底，避免成本显示为 0
MODEL_PRICES: dict[str, dict[str, float]] = {
    "deepseek-v4-pro":      {"input": 0.014, "output": 0.028},
    "deepseek-v3":          {"input": 0.002, "output": 0.008},
    "deepseek-chat":        {"input": 0.002, "output": 0.008},
    "deepseek-reasoner":    {"input": 0.014, "output": 0.028},
    "gpt-4o":               {"input": 0.005, "output": 0.015},
    "gpt-4o-mini":          {"input": 0.00015, "output": 0.0006},
    "claude-3-5-sonnet":    {"input": 0.003, "output": 0.015},
}

DEFAULT_PRICE = {"input": 0.003, "output": 0.015}  # 未知模型兜底


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """按模型单价估算单次调用的美元成本。"""
    prices = MODEL_PRICES.get(model, DEFAULT_PRICE)
    return (input_tokens / 1000.0) * prices["input"] + (output_tokens / 1000.0) * prices["output"]


# ── Span 模型 ─────────────────────────────────────────────


def _now_ms() -> int:
    return int(time.time() * 1000)


def make_span(
    span_type: str,
    session_id: str,
    *,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
    tool_name: str = "",
    tool_args: Any = None,
    result: str = "",
    is_error: bool = False,
    duration_ms: float = 0.0,
    finish_reason: str = "",
    brain: str = "",
    turn: int = 0,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """构造一个 span 事件 dict（jsonl 一行）。"""
    span: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": span_type,
        "session_id": session_id,
        "turn": turn,
        "duration_ms": round(duration_ms, 2),
        "is_error": bool(is_error),
    }
    if span_type == "llm":
        span["model"] = model
        span["input_tokens"] = int(input_tokens or 0)
        span["output_tokens"] = int(output_tokens or 0)
        span["total_tokens"] = int(input_tokens or 0) + int(output_tokens or 0)
        span["cost"] = round(cost, 6)
        span["finish_reason"] = finish_reason
    elif span_type == "tool":
        span["tool"] = tool_name
        if tool_args is not None:
            span["args"] = tool_args
        span["result"] = (result or "")[:2000]  # 截断避免巨量结果撑爆 jsonl
        span["result_truncated"] = len(result or "") > 2000
    elif span_type == "brain":
        span["brain"] = brain
        span["tool"] = tool_name
    if extra:
        span["extra"] = extra
    return span


# ── TraceRecorder ─────────────────────────────────────────


class TraceRecorder:
    """会话级 trace 收集器：异步队列 → jsonl 落盘，不阻塞 agent 循环。"""

    def __init__(self, session_id: str, project_root: str = "."):
        self.session_id = session_id
        self.project_root = project_root
        self._queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._writer_task: Optional[asyncio.Task] = None
        self._running = False
        self._log_path: Optional[Path] = None
        self._spans: list[dict[str, Any]] = []  # 内存副本，供 /api/traces 实时读取
        self._lock = asyncio.Lock()

    async def start(self):
        if self._running:
            return
        self._running = True
        trace_dir = Path(self.project_root) / TRACE_DIR
        trace_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = trace_dir / f"{self.session_id}.jsonl"
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def stop(self):
        if not self._running:
            return
        self._running = False
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if self._writer_task:
            try:
                await asyncio.wait_for(self._writer_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._writer_task.cancel()

    async def record(self, span: dict[str, Any]):
        """记录一个 span（不阻塞调用方）。"""
        if not self._running:
            return
        async with self._lock:
            self._spans.append(span)
        try:
            self._queue.put_nowait(json.dumps(span, ensure_ascii=False, default=str))
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(json.dumps(span, ensure_ascii=False, default=str))
            except Exception:
                pass

    async def spans_snapshot(self) -> list[dict[str, Any]]:
        """返回当前内存中的全部 span（供 API 读取）。"""
        async with self._lock:
            return list(self._spans)

    async def _writer_loop(self):
        assert self._log_path is not None
        batch: list[str] = []
        while self._running or not self._queue.empty():
            try:
                entry = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                if batch:
                    self._flush(batch)
                    batch = []
                continue
            if entry is None:
                break
            batch.append(entry)
            if len(batch) >= 20:
                self._flush(batch)
                batch = []
        if batch:
            self._flush(batch)

    def _flush(self, entries: list[str]):
        if not entries or not self._log_path:
            return
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                for e in entries:
                    f.write(e + "\n")
        except Exception as exc:
            logger.warning("Trace write failed: %s", exc)


# ── 全局注册表（按 session 复用）──────────────────────────

_recorders: dict[str, TraceRecorder] = {}


def get_recorder(session_id: str, project_root: str = ".") -> TraceRecorder:
    """获取（或创建）会话级 recorder。"""
    key = f"{project_root}:{session_id}"
    if key not in _recorders:
        _recorders[key] = TraceRecorder(session_id, project_root)
    return _recorders[key]


async def close_recorder(session_id: str, project_root: str = "."):
    """停止并清理 recorder。"""
    key = f"{project_root}:{session_id}"
    rec = _recorders.pop(key, None)
    if rec:
        await rec.stop()


# ── 磁盘读取（历史回放）───────────────────────────────────


def load_trace_file(session_id: str, project_root: str = ".") -> list[dict[str, Any]]:
    """从磁盘读回一次会话的完整 trace（历史回放用）。"""
    path = Path(project_root) / TRACE_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return []
    spans: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                spans.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception as exc:
        logger.warning("Trace load failed: %s", exc)
    return spans


def list_trace_sessions(project_root: str = ".") -> list[dict[str, Any]]:
    """列出项目下所有有 trace 的会话（含统计摘要）。"""
    trace_dir = Path(project_root) / TRACE_DIR
    if not trace_dir.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for f in sorted(trace_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        spans = load_trace_file(f.stem, project_root)
        if not spans:
            continue
        total_tokens = sum(
            s.get("total_tokens", 0) for s in spans if s.get("type") == "llm"
        )
        total_cost = sum(
            s.get("cost", 0.0) for s in spans if s.get("type") == "llm"
        )
        tool_count = sum(1 for s in spans if s.get("type") == "tool")
        sessions.append({
            "session_id": f.stem,
            "spans": len(spans),
            "llm_calls": sum(1 for s in spans if s.get("type") == "llm"),
            "tool_calls": tool_count,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 6),
            "updated_at": f.stat().st_mtime,
        })
    return sessions


# ── 聚合统计（一个 session 的 trace → 摘要）────────────────


def summarize_trace(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """把 span 列表压成会话级摘要（前端聚合条用）。"""
    llm_spans = [s for s in spans if s.get("type") == "llm"]
    tool_spans = [s for s in spans if s.get("type") == "tool"]
    brain_spans = [s for s in spans if s.get("type") == "brain"]
    error_tools = [s for s in tool_spans if s.get("is_error")]

    tool_failures: dict[str, int] = {}
    for s in error_tools:
        name = s.get("tool", "?")
        tool_failures[name] = tool_failures.get(name, 0) + 1

    return {
        "llm_calls": len(llm_spans),
        "tool_calls": len(tool_spans),
        "brain_calls": len(brain_spans),
        "input_tokens": sum(s.get("input_tokens", 0) for s in llm_spans),
        "output_tokens": sum(s.get("output_tokens", 0) for s in llm_spans),
        "total_tokens": sum(s.get("total_tokens", 0) for s in llm_spans),
        "total_cost": round(sum(s.get("cost", 0.0) for s in llm_spans), 6),
        "total_duration_ms": round(sum(s.get("duration_ms", 0) for s in spans), 2),
        "tool_errors": len(error_tools),
        "tool_failures_top": dict(sorted(tool_failures.items(), key=lambda x: -x[1])[:5]),
        "models": sorted({s.get("model", "") for s in llm_spans if s.get("model")}),
    }
