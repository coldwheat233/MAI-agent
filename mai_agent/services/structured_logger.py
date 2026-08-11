"""Structured Logging Service — JSON-lines, AI-determined granularity, async queue.

Separate from Python's logging module. Design:
  - One .jsonl file per session in .mai/logs/
  - Each line: {"ts": "...", "level": "INFO", "event": "tool_call", "data": {...}}
  - Async writer task drains a queue → never blocks the agent loop
  - Level determination: heuristic (event → level) + optional LLM override
  - Auto-flush on turn boundaries, tool calls, memory extraction

Level semantics:
  TRACE — tool input/output detail
  DEBUG — brain internal state, reasoning steps
  INFO  — milestone events (turn start, tool selected, converged)
  WARN  — recoverable issues (tool error, unknown concept)
  ERROR — unrecoverable failures (LLM error, crash)
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

LOG_DIR = ".mai/logs"
QUEUE_SIZE = 200  # Drop oldest if exceeding this


# ── Level determination (heuristic) ────────────────────────

EVENT_LEVELS = {
    "tool_call": "TRACE",
    "tool_result": "TRACE",
    "tool_error": "WARN",
    "turn_start": "DEBUG",
    "turn_converge": "INFO",
    "unknown_concept": "WARN",
    "memory_extract": "INFO",
    "session_start": "INFO",
    "session_end": "INFO",
    "permission_deny": "WARN",
    "brain_activate": "DEBUG",
    "brain_complete": "INFO",
    "error": "ERROR",
}


def _determine_level(event: str, is_error: bool = False) -> str:
    """Map event type to log level. ERROR overrides all."""
    if is_error:
        return "ERROR"
    return EVENT_LEVELS.get(event, "DEBUG")


# ── Structured Logger ─────────────────────────────────────


class StructuredLogger:
    """JSON-lines structured logger with async background writer."""

    def __init__(self, session_id: str, project_root: str = "."):
        self.session_id = session_id
        self.project_root = project_root
        self._queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._writer_task: Optional[asyncio.Task] = None
        self._running = False
        self._log_path: Optional[Path] = None
        self._count = 0
        self._total_writes = 0

    async def start(self):
        """Start the background writer task."""
        if self._running:
            return
        self._running = True

        # Ensure log directory
        log_dir = Path(self.project_root) / LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)

        # One file per session
        self._log_path = log_dir / f"{self.session_id}.jsonl"

        # Write header
        header = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "event": "session_start",
            "data": {"session_id": self.session_id},
        }, ensure_ascii=False)
        self._log_path.write_text(header + "\n", encoding="utf-8")
        self._total_writes += 1

        self._writer_task = asyncio.create_task(self._writer_loop())

    async def stop(self):
        """Stop the writer task and flush remaining entries."""
        if not self._running:
            return
        self._running = False

        # Signal writer to stop (no extra entry — engine.stop() handles session_end)
        self._queue.put_nowait(None)

        if self._writer_task:
            try:
                await asyncio.wait_for(self._writer_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._writer_task.cancel()

    def log(
        self,
        event: str,
        data: Optional[dict[str, Any]] = None,
        level: Optional[str] = None,
        is_error: bool = False,
    ):
        """Enqueue a log entry. Non-blocking — never blocks the agent loop.

        Args:
            event: Event type (tool_call, turn_start, etc.)
            data: Arbitrary structured data
            level: Override heuristic level. If None, auto-determined.
            is_error: Force ERROR level
        """
        if not self._running:
            return

        resolved_level = "ERROR" if is_error else (level or _determine_level(event, is_error))

        entry = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": resolved_level,
            "event": event,
            "data": data or {},
        }, ensure_ascii=False, default=str)

        try:
            self._queue.put_nowait(entry)
            self._count += 1
        except asyncio.QueueFull:
            # Drop oldest to make room (never block)
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(entry)
            except Exception:
                pass  # Best-effort

    async def _writer_loop(self):
        """Background task: drain queue → write to file."""
        assert self._log_path is not None
        batch: list[str] = []

        while self._running or not self._queue.empty():
            try:
                entry = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                # Flush batch even if queue is idle
                if batch:
                    self._flush_batch(batch)
                    batch = []
                continue

            if entry is None:  # Sentinel
                break

            batch.append(entry)

            # Flush every 10 entries or if queue is empty
            if len(batch) >= 10:
                self._flush_batch(batch)
                batch = []

        # Final flush
        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, entries: list[str]):
        """Write a batch of log entries to file."""
        if not entries or not self._log_path:
            return
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                for e in entries:
                    f.write(e + "\n")
            self._total_writes += len(entries)
        except Exception as exc:
            logger.warning("Log write failed: %s", exc)

    @property
    def path(self) -> Optional[Path]:
        return self._log_path

    @property
    def count(self) -> int:
        return self._count


# ── Global log factory ────────────────────────────────────

_logger_instances: dict[str, StructuredLogger] = {}


def get_logger(session_id: str, project_root: str = ".") -> StructuredLogger:
    """Get or create a structured logger for a session."""
    key = f"{project_root}:{session_id}"
    if key not in _logger_instances:
        _logger_instances[key] = StructuredLogger(session_id, project_root)
    return _logger_instances[key]


async def close_logger(session_id: str, project_root: str = "."):
    """Close and flush a session's logger."""
    key = f"{project_root}:{session_id}"
    log = _logger_instances.pop(key, None)
    if log:
        await log.stop()
