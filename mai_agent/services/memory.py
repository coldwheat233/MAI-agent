"""Session Memory — upgraded to Claude Code standards.

Differences from v1:
  1. Dual threshold: token delta + tool call count (not just tool count)
  2. Safe window: only extract when last assistant turn has no pending tool_calls
  3. Isolated context: separate RunContext for reading memory file
  4. Concurrency guard: asyncio.Lock prevents concurrent extractions
  5. Message-position tracking: track extraction by message index, not simple counter
  6. Template init: first-time memory file gets a template header
  7. Stale protection: timeout for stuck extractions
  8. Manual trigger: /summary command compatible
  9. Token estimation: count context tokens for threshold decisions
  10. PostSamplingHook pattern: can be called after each llm response
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mai_agent.core.models import Message
from mai_agent.llm.client import LLMClient

logger = logging.getLogger(__name__)

MEMORY_FILE = "SESSION_MEMORY.md"
EXTRACTION_STALE_SEC = 60.0  # Stale threshold

# ── Config (defaults, can be overridden) ──────────────────

DEFAULT_CONFIG = {
    "min_tokens_to_init": 1000,        # Must accumulate this many tokens before first extraction
    "min_tokens_between_update": 500,   # Must grow by this much since last extraction
    "tool_calls_between_update": 3,     # At least this many tool calls since last
}

_current_config: dict[str, int] = {**DEFAULT_CONFIG}

# ── Module state ──────────────────────────────────────────

_last_extraction_index: int = -1   # Message index (position in list) of last extraction
_initialized: bool = False         # Has min_tokens_to_init been met?
_tokens_at_last_extraction: int = 0
_extraction_lock = asyncio.Lock()
_extraction_started_at: float = 0.0
_session_start_index: int = 0      # Index of first message in current session


def set_config(**kwargs: int) -> None:
    """Override default thresholds. e.g. set_config(min_tokens_to_init=5000)."""
    _current_config.update(kwargs)


def reset_state() -> None:
    """Reset all module state (for new session)."""
    global _last_extraction_index, _initialized, _tokens_at_last_extraction
    global _extraction_started_at, _session_start_index
    _last_extraction_index = -1
    _initialized = False
    _tokens_at_last_extraction = 0
    _extraction_started_at = 0.0
    _session_start_index = 0


# ── Threshold logic (dual: tokens + tool calls) ───────────


def _estimate_tokens(messages: list[Message]) -> int:
    """Rough token count: ~4 chars per token."""
    total = 0
    for m in messages:
        if m.content:
            total += len(m.content) // 4
        if m.tool_calls:
            for tc in m.tool_calls:
                total += len(tc.function.arguments) // 4 if tc.function else 0
    return total


def _count_tool_calls_since(messages: list[Message], since_index: int) -> int:
    """Count tool calls from messages after since_index."""
    count = 0
    for i in range(max(0, since_index + 1), len(messages)):
        m = messages[i]
        if m.tool_calls:
            count += len(m.tool_calls)
    return count


def _last_turn_has_pending_tools(messages: list[Message]) -> bool:
    """Check if the last assistant message has unresolved tool_calls.

    Only returns True if the LAST assistant message has tool_calls
    AND no tool_result follows it (meaning tools are still executing).
    """
    # Find the last assistant message with tool_calls
    last_assistant_idx = -1
    for i, m in enumerate(messages):
        if m.role == "assistant" and m.tool_calls:
            last_assistant_idx = i

    if last_assistant_idx == -1:
        return False  # No assistant with tool_calls

    # Check if there's a tool result AFTER this assistant
    has_result_after = any(
        m.role == "tool" for m in messages[last_assistant_idx + 1:]
    )
    return not has_result_after  # Pending if no result yet


def should_extract(messages: list[Message]) -> bool:
    """Determine if memory extraction should trigger.

    Claude Code logic:
      1. Has the context reached min_tokens_to_init? (if not → init and return False)
      2. Has context grown by min_tokens_between_update since last extraction?
      3. Have enough tool calls accumulated since last extraction?
      4. Is the last turn "safe" (no pending tool_calls)?
    """
    global _initialized, _tokens_at_last_extraction

    if len(messages) < 4:
        return False

    current_tokens = _estimate_tokens(messages)

    # Initialization check
    if not _initialized:
        if current_tokens >= _current_config["min_tokens_to_init"]:
            _initialized = True
            logger.info("SessionMemory initialized at %d tokens", current_tokens)
        else:
            return False

    # Token growth since last extraction
    token_delta = current_tokens - _tokens_at_last_extraction
    if token_delta < _current_config["min_tokens_between_update"]:
        return False

    # Tool call count since last extraction
    tool_count = _count_tool_calls_since(messages, _last_extraction_index)
    if tool_count < _current_config["tool_calls_between_update"]:
        return False

    # Safe window: don't extract mid-action
    if _last_turn_has_pending_tools(messages):
        return False

    return True


# ── Core extraction logic ─────────────────────────────────

MEMORY_TEMPLATE = """# Session Memory

This file is maintained automatically by MAI-agent.
It captures key decisions, file changes, unresolved questions,
and knowledge gained across conversations.

---

"""

EXTRACT_PROMPT = """You are a session memory extractor. Your job is to maintain SESSION_MEMORY.md.

Read the existing memory file, then append ONLY new information from the latest conversation:
  - Key decisions made and WHY
  - Files created, modified, or deleted
  - Unresolved questions or blockers
  - Concepts the user learned or asked about

Rules:
  - Do NOT repeat information already in the memory file
  - If a previous open question is now resolved, mark it [RESOLVED]
  - Use the format: ## YYYY-MM-DD HH:MM / ### section / - item
  - Keep entries concise (1-2 lines each)
  - When a concept has a corresponding tagged memory card, link it with [[name]]
    (e.g. "实现分布式锁 [[distributed-lock]]"). Unknown [[name]] links are fine —
    they mark something worth writing a card for later.
"""


def memory_path(project_root: str = ".") -> Path:
    return Path(project_root) / ".mai" / MEMORY_FILE


def load_memory(project_root: str = ".") -> Optional[str]:
    path = memory_path(project_root)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _ensure_memory_file(project_root: str) -> str:
    """Create memory file with template if it doesn't exist. Returns current content."""
    path = memory_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(MEMORY_TEMPLATE, encoding="utf-8")
        return MEMORY_TEMPLATE
    return path.read_text(encoding="utf-8")


def memory_context_for_prompt(project_root: str = ".") -> str:
    """Build a context block from memory for injection into system prompt."""
    mem = load_memory(project_root)
    if not mem or len(mem) < 50:
        return ""
    truncated = mem[-3000:] if len(mem) > 3000 else mem
    return (
        "[Session Memory — from previous conversations]\n"
        f"{truncated}\n"
        "[End Session Memory]"
    )


async def extract_and_persist(
    messages: list[Message],
    project_root: str = ".",
    api_key: str = "",
    base_url: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-v4-pro",
) -> Optional[str]:
    """Run memory extraction subagent and persist to disk.

    Uses asyncio.Lock to prevent concurrent extractions.
    Has stale protection: if a previous extraction is stuck >60s, force-override.
    """
    global _last_extraction_index, _tokens_at_last_extraction, _extraction_started_at

    # Concurrency guard with stale protection
    now = asyncio.get_event_loop().time()
    if _extraction_lock.locked():
        if _extraction_started_at > 0 and (now - _extraction_started_at) < EXTRACTION_STALE_SEC:
            logger.debug("Extraction already in progress, skipping")
            return None
        # Stale — force release
        logger.warning("Previous extraction stale, forcing new one")
        try:
            _extraction_lock.release()
        except RuntimeError:
            pass

    async with _extraction_lock:
        _extraction_started_at = now

        try:
            result = await _do_extract(messages, project_root, api_key, base_url, model)
            if result:
                _last_extraction_index = len(messages) - 1
                _tokens_at_last_extraction = _estimate_tokens(messages)
            return result
        except Exception as exc:
            logger.warning("Memory extraction failed: %s", exc)
            return None
        finally:
            _extraction_started_at = 0.0


async def _do_extract(
    messages: list[Message],
    project_root: str,
    api_key: str,
    base_url: str,
    model: str,
) -> Optional[str]:
    """Actual extraction logic."""
    # Ensure file exists with template
    current_memory = _ensure_memory_file(project_root)

    # Build conversation summary
    conv_text = _messages_to_text(messages[-30:])
    prompt = (
        f"{EXTRACT_PROMPT}\n\n"
        f"--- EXISTING MEMORY ---\n{current_memory}\n--- END EXISTING ---\n\n"
        f"--- LATEST CONVERSATION ---\n{conv_text}\n--- END CONVERSATION ---\n\n"
        f"Use the Write tool to write ONLY the new information from this conversation "
        f"(2-3 bullet points). Do NOT repeat the existing memory above — it is preserved automatically."
    )

    llm = LLMClient(api_key=api_key, base_url=base_url, model=model)
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": prompt},
    ]

    # Turn 1: Read existing memory
    response = await llm.chat(msgs, tools=[
        _tool_schema("Read", "Read a file"),
    ])

    if response.tool_calls:
        msgs.append(_assistant_msg(response))
        for tc in response.tool_calls:
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": current_memory,
            })

    # Turn 2: Write updated memory (only allows Write to memory file)
    response2 = await llm.chat(msgs, tools=[
        _tool_schema("Write", "Write a file"),
    ])

    if response2.tool_calls:
        for tc in response2.tool_calls:
            args = _safe_json(tc.function.arguments if tc.function else "{}")
            content = args.get("content", "")
            if content:
                # 追加式落盘——绝不整文件覆盖（覆盖会抹掉历史）
                _append_memory(project_root, content)
                logger.info("Session memory appended (%d chars)", len(content))
                return content

    # Fallback: model returned text directly
    if response2.content:
        _append_memory(project_root, response2.content)
        logger.info("Session memory appended (%d chars)", len(response2.content))
        return response2.content

    return None


async def manual_extract(
    messages: list[Message],
    project_root: str = ".",
    api_key: str = "",
    base_url: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-v4-pro",
) -> dict[str, Any]:
    """Manual extraction — bypasses threshold checks. Use for /summary."""
    if not messages:
        return {"success": False, "error": "No messages to summarize"}

    try:
        result = await _do_extract(messages, project_root, api_key, base_url, model)
        if result:
            return {"success": True, "memory_path": str(memory_path(project_root))}
        return {"success": False, "error": "Extraction produced no output"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Helpers ───────────────────────────────────────────────


def _append_memory(project_root: str, content: str) -> None:
    path = memory_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else MEMORY_TEMPLATE
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## {timestamp}\n\n{content}\n"
    path.write_text(existing + entry, encoding="utf-8")


def _messages_to_text(messages: list[Message]) -> str:
    lines: list[str] = []
    for m in messages[-30:]:
        role = m.role
        if m.content:
            text = m.content[:800]
            lines.append(f"[{role}] {text}")
        if m.tool_calls:
            for tc in m.tool_calls:
                fn = tc.function.name if tc.function else "?"
                lines.append(f"[{role} → {fn}]")
    return "\n".join(lines)


def _tool_schema(name: str, desc: str) -> dict:
    if name == "Read":
        properties = {"file_path": {"type": "string"}}
        required = ["file_path"]
    else:  # Write
        properties = {"content": {"type": "string"}}
        required = ["content"]
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _assistant_msg(response: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant"}
    if response.content:
        msg["content"] = response.content
    if response.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name if tc.function else "", "arguments": tc.function.arguments if tc.function else "{}"},
            }
            for tc in response.tool_calls
        ]
    return msg


def _safe_json(s: str) -> dict[str, Any]:
    import json as _json
    try:
        return _json.loads(s)
    except Exception:
        return {}
