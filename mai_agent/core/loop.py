"""Agent 核心循环 — 对应 Claude Code 的 query.ts。

"思考—行动—观察" 循环:
  1. 调用 LLM(messages + tools)
  2. 解析响应: 纯文本→收敛结束 / tool_calls→执行工具
  3. 工具结果追加回 messages
  4. 回到步骤 1，直到收敛或达到最大步数

这是整个 MAI-agent 最核心的代码，不依赖任何 Agent 框架。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

from mai_agent.core.models import (
    Message,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ToolResultMessage,
    ToolCall,
    ToolResultBlock,
)
from mai_agent.llm.client import LLMClient, LLMResponse
from mai_agent.tools.base import RunContext
from mai_agent.tools.registry import ToolRegistry
from mai_agent.tools.orchestration import (
    ToolUseBlock,
    run_tools,
    ToolExecutionResult,
)

logger = logging.getLogger(__name__)

# ── Progress callback protocol ───────────────────────────


@dataclass
class StepProgress:
    """Emitted by agent_loop for CLI visibility."""
    step: int
    max_steps: int
    event: str  # "thinking" | "text" | "tool_start" | "tool_result" | "converge"
    tool_name: str = ""
    tool_args: str = ""      # brief (truncated) args string
    tool_result: str = ""    # brief (truncated) result
    text: str = ""           # streaming text delta
    is_error: bool = False
    tokens_used: int = 0     # cumulative tokens this turn
    context_tokens: int = 0  # estimated total context token count
    max_context_tokens: int = 0  # config.max_context_tokens

ProgressCallback = Callable[[StepProgress], Awaitable[None]] | None


# ── 消息转换 ─────────────────────────────────────────────


def messages_to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    """将内部 Message 列表转为 OpenAI API 格式。"""
    result: list[dict[str, Any]] = []
    for m in messages:
        msg: dict[str, Any] = {"role": m.role}
        if m.content is not None:
            msg["content"] = m.content
        if m.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name if tc.function else "",
                        "arguments": tc.function.arguments if tc.function else "{}",
                    },
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        result.append(msg)
    return result


# ── Agent Loop Config ────────────────────────────────────


@dataclass
class AgentLoopConfig:
    """Agent 循环配置"""
    max_turns: int = 50
    temperature: float = 0.0
    permission_mode: str = "auto"
    ask_permission: Any = None  # async fn(tool_name, args) -> bool
    max_context_tokens: int = 100_000  # 上下文窗口上限（deepseek = 128K，留余量）
    system_prompt: str = (
        "你是一个帮助开发者完成任务的 AI 助手。\n"
        "你可以使用提供的工具来读取文件、搜索代码、执行命令、孵化子Agent。\n\n"
        "规则:\n"
        "1. 当需要分析需求或生成计划时，使用 Agent 工具激活 dev_explorer 脑\n"
        "2. 当需要验证代码或运行测试时，使用 Agent 工具激活 dev_validator 脑\n"
        "3. 当需要查看文件内容时使用 Read 工具\n"
        "4. 当需要搜索代码时使用 Grep 工具\n"
        "5. 当需要执行命令时使用 Bash 工具\n"
        "6. 当需要修改文件时使用 Edit 工具\n"
        "7. 当需要创建文件时使用 Write 工具\n"
        "8. 每次只做一轮工具调用，观察结果后再决定下一步\n"
        "9. 最终回答直接用中文，不要再输出函数调用\n"
        "10. 如果工具返回错误，据此调整策略或告知用户"
    )


# ── Agent Loop ────────────────────────────────────────────


async def agent_loop(
    user_input: str,
    llm: LLMClient,
    registry: ToolRegistry,
    context: RunContext,
    config: AgentLoopConfig,
    initial_messages: Optional[list[Message]] = None,
    on_progress: ProgressCallback = None,
    _skip_user_append: bool = False,
) -> tuple[str, list[Message]]:
    """Agent 核心循环 — 对应 Claude Code 的 query() 函数。

    流程:
        while turn < max_turns:
            response = LLM(messages, tools)
            append assistant message
            if no tool_calls:
                return response.content  ← 收敛
            for each tool_call:
                result = execute tool
                append tool_result message

    Args:
        user_input: 用户输入文本
        llm: LLM 客户端
        registry: 工具注册表
        context: 工具执行上下文
        config: 循环配置
        initial_messages: 已有的历史消息（用于 session 恢复）

    Returns:
        (final_answer, all_messages) — 最终回答 + 完整消息历史
    """
    # 1. 初始化 messages
    messages: list[Message] = list(initial_messages) if initial_messages else []

    if not any(m.role == "system" for m in messages):
        messages.insert(0, SystemMessage(content=config.system_prompt))

    # ── 脑上下文注入 ──
    # 先清除上次脑注入的残留 SystemMessage（避免重复/脑切换后残留）
    messages = [m for m in messages if not (
        m.role == "system" and m.content.startswith("[当前激活:")
    )]
    if context.active_brain:
        from mai_agent.brains.definitions import ALL_BRAINS
        brain_def = ALL_BRAINS.get(context.active_brain)
        if brain_def:
            # 将脑的专用 prompt 注入为额外的 system message
            brain_msg = SystemMessage(
                content=(
                    f"[当前激活: {brain_def.name} — {brain_def.description}]\n\n"
                    f"{brain_def.prompt}\n\n"
                    f"[脑指令结束 — 请遵循上述角色设定完成当前任务]"
                )
            )
            # 插入到 system prompt 之后、任何其他消息之前
            messages.insert(1, brain_msg)

    messages.append(UserMessage(content=user_input)) if not _skip_user_append else None
    tools = registry.to_openai_schemas(config.permission_mode)

    # 2. 主循环（整体包一层 CancelledError 兜底：被 stop 硬取消时，
    #    把已流出的部分内容落进 messages，避免“答了一半”丢失）
    step = 0
    content_text = ""
    text_buf = ""
    step_committed = True  # 当前 step 的 assistant 消息是否已追加进 messages
    try:
      for step in range(1, config.max_turns + 1):
        # 中断检查
        if context.is_aborted():
            logger.info("Agent 被中断 (step %d)", step)
            return "(Interrupted by user.)", messages

        logger.info("Step %d/%d — calling LLM (stream)", step, config.max_turns)

        # ── 上下文窗口管理: 超 80% 时自动压缩 ──
        if config.max_context_tokens > 0:
            ctx_tok = _count_context_tokens(messages, config.system_prompt)
            threshold = int(config.max_context_tokens * 0.8)
            if ctx_tok > threshold:
                logger.warning(
                    "上下文 %d tokens 超过阈值 %d，触发压缩",
                    ctx_tok, threshold,
                )
                messages = await _compact_context(
                    messages, llm, config.system_prompt,
                    keep_last=8,  # 保留最近 8 条（至少 2 轮工具对话）
                )
                if on_progress:
                    await on_progress(StepProgress(
                        step=step, max_steps=config.max_turns,
                        event="text", text=f"[上下文压缩: {ctx_tok} → {_count_context_tokens(messages, config.system_prompt)} tokens]",
                    ))

        # Emit progress: thinking
        if on_progress:
            await on_progress(StepProgress(
                step=step, max_steps=config.max_turns, event="thinking",
            ))

        # 调用 LLM (streaming)
        openai_messages = messages_to_openai(messages)
        content_text = ""
        final_tool_calls = None
        final_usage = None
        text_buf = ""  # Batch text deltas to reduce progress events
        step_committed = False  # 本 step 的 assistant 消息尚未落进 messages
        stream_error: str | None = None  # Salvaged on mid-stream failure

        try:
            async for text_delta, tc_delta, fin, *rest in llm.chat_stream(openai_messages, tools=tools):
                # 流中中断检查
                if context.is_aborted():
                    logger.info("Agent 流中被中断 (step %d)", step)
                    break
                if text_delta:
                    content_text += text_delta
                    text_buf += text_delta
                    # Batch: emit only every ~20 chars or when a sentence ends
                    if on_progress and (len(text_buf) >= 20 or text_delta.rstrip().endswith((".", "。", "\n", "!", "?", "！", "？"))):
                        await on_progress(StepProgress(
                            step=step, max_steps=config.max_turns,
                            event="text", text=text_buf,
                        ))
                        text_buf = ""
                if tc_delta is not None:
                    final_tool_calls = tc_delta
                # usage arrives as optional 4th element in the final yield tuple
                if rest:
                    final_usage = rest[0]
        except Exception as exc:
            logger.warning("LLM stream error: %s", exc)
            stream_error = f"(stream interrupted: {exc})"
            # If we got some content + no tool_calls → treat as convergence with salvaged text
            if content_text and not final_tool_calls:
                content_text += f"\n\n{stream_error}"
            elif not content_text:
                # Nothing salvaged → re-raise
                raise

        # Flush remaining batched text
        if text_buf and on_progress:
            await on_progress(StepProgress(
                step=step, max_steps=config.max_turns,
                event="text", text=text_buf,
            ))

        # Build pseudo-response for message history
        response = LLMResponse(
            content=content_text or None,
            tool_calls=final_tool_calls,
            finish_reason="stop",
            usage=final_usage,
        )

        # 追加 assistant 消息
        assistant_msg = AssistantMessage(
            content=response.content or "",
            tool_calls=_to_model_toolcalls(response.tool_calls),
        )
        messages.append(assistant_msg)
        step_committed = True

        # 没有 tool_calls → 收敛
        if not response.tool_calls:
            logger.info("Step %d — converged", step)
            # Estimate context token count
            context_tok = _count_context_tokens(messages, config.system_prompt)
            if on_progress:
                await on_progress(StepProgress(
                    step=step, max_steps=config.max_turns,
                    event="converge", tool_result=(response.content or "")[:200],
                    tokens_used=(final_usage.total_tokens if final_usage else 0),
                    context_tokens=context_tok,
                    max_context_tokens=config.max_context_tokens,
                ))
            return response.content or "(empty)", messages

        # 有 tool_calls → 转换 + 执行
        blocks = [
            ToolUseBlock(
                id=tc.id,
                name=tc.function.name if tc.function else "",
                input=_parse_tool_args(tc),
            )
            for tc in response.tool_calls
        ]

        logger.info("Step %d — %d tool calls: %s",
                    step, len(blocks), [b.name for b in blocks])

        # ── 权限门控 PreToolUse hooks ──
        # 对所有工具跑 can_use_tool（auto 模式直接放行，plan 限只读，manual 跑 hook 链）
        from mai_agent.hooks.gate import can_use_tool

        denied_blocks: set[int] = set()
        for i, b in enumerate(blocks):
            permission = await can_use_tool(
                tool_name=b.name,
                tool_input=b.input,
                permission_mode=config.permission_mode,
            )
            # Hook 可能修改工具输入参数
            if permission.modified_input:
                b.input = permission.modified_input
            if not permission.allow:
                # Hook 链拒绝了此工具
                reason = permission.reason or f"工具 '{b.name}' 被权限策略拦截"
                # 手动模式下通过 ask_permission 回调给用户选择
                if (permission.reason and "需要确认" in permission.reason
                        and config.ask_permission):
                    user_allowed = await config.ask_permission(b.name, b.input)
                    if user_allowed:
                        continue  # 用户放行
                    reason = f"用户拒绝: {b.name}"
                messages.append(ToolResultMessage(
                    role="tool",
                    content=f"[DENIED] {reason}",
                    tool_call_id=b.id,
                ))
                if on_progress:
                    await on_progress(StepProgress(
                        step=step, max_steps=config.max_turns,
                        event="tool_result",
                        tool_name=b.name,
                        tool_result=f"[DENIED] {reason[:60]}",
                        is_error=True,
                    ))
                denied_blocks.add(i)

        # Remove denied blocks (work from end to preserve indices)
        blocks = [b for i, b in enumerate(blocks) if i not in denied_blocks]

        if not blocks:
            continue  # All tools denied, go to next loop iteration

        # Emit tool_start for each tool
        if on_progress:
            for b in blocks:
                await on_progress(StepProgress(
                    step=step, max_steps=config.max_turns,
                    event="tool_start",
                    tool_name=b.name,
                    tool_args=_truncate(json.dumps(b.input, ensure_ascii=False), 80),
                ))

        # Wire stream callback so tools (like Bash) can emit real-time output
        if on_progress:
            async def _stream_cb(text: str):
                await on_progress(StepProgress(
                    step=step, max_steps=config.max_turns,
                    event="text", text=text,
                ))
            context.stream_callback = _stream_cb

        # Execute tools with progress events
        exec_results: list[ToolExecutionResult] = []
        async for result in run_tools(blocks, registry, context):
            exec_results.append(result)

        # Clear stream callback after execution
        context.stream_callback = None

        # Append tool results + emit progress
        for block, exec_result in zip(blocks, exec_results):
            mr = exec_result.message
            messages.append(
                ToolResultMessage(
                    role="tool",
                    content=mr.content,
                    tool_call_id=mr.tool_use_id,
                )
            )
            # Emit progress: tool call done
            if on_progress:
                await on_progress(StepProgress(
                    step=step, max_steps=config.max_turns,
                    event="tool_result",
                    tool_name=block.name,
                    tool_args=_truncate(str(block.input), 80),
                    tool_result=_truncate(mr.content, 120),
                    is_error=mr.is_error,
                ))

    except asyncio.CancelledError:
        # 被 stop 硬取消（或引擎热替换）。把中断前已流出的部分内容
        # 落进 messages，保证“答了一半”的状态可持久化、可恢复。
        logger.info("Agent 循环被取消 (step %d)", step)
        if text_buf and on_progress:
            try:
                await on_progress(StepProgress(
                    step=step, max_steps=config.max_turns,
                    event="text", text=text_buf,
                ))
            except Exception:
                pass
        partial = content_text.strip()
        if not step_committed and partial:
            messages.append(AssistantMessage(content=partial))
        # 清理可能被取消打断的不完整 tool_calls——否则下次加载会话再提交就 400
        messages = strip_incomplete_tool_calls(messages)
        note = f"{partial}\n\n(已被用户停止)" if partial else "(已被用户停止)"
        return note, messages

    # 3. Fallback: max turns exhausted (safety limit)
    messages = strip_incomplete_tool_calls(messages)
    return "(Task complexity exceeds turn limit. Please break it down into smaller steps or check for looping.)", messages


# ── 辅助函数 ─────────────────────────────────────────────


def strip_incomplete_tool_calls(messages: list[Message]) -> list[Message]:
    """清洗不完整的 tool_calls 序列。

    DeepSeek/OpenAI 要求 assistant(tool_calls) 后面必须紧跟等量的 tool 回复，
    否则 API 直接 400。中断/异常时可能产生不完整序列——把最后一段残缺的切掉。
    """
    # 从尾部向前找：每条 assistant 的 tool_calls 是否都有对应的 tool 消息
    tool_call_ids: set[str] = set()
    # 先收集所有 tool 消息的 id
    for m in messages:
        if m.role == "tool" and m.tool_call_id:
            tool_call_ids.add(m.tool_call_id)
    # 从尾部向前，找第一个有 tool_calls 但缺 tool 回复的 assistant 消息
    cut_at = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.role == "assistant" and m.tool_calls:
            # 检查这条 assistant 的所有 tool_call_id 是否都有对应的 tool 消息
            all_present = True
            for tc in m.tool_calls:
                if tc.id not in tool_call_ids:
                    all_present = False
                    break
            if not all_present:
                # 从这里截断
                cut_at = i
            break  # 只检查最后一条 assistant(tool_calls)
    if cut_at < len(messages):
        logger.warning(
            "清洗不完整 tool_calls: 从 index=%d 截断 (%d 条消息移除)",
            cut_at, len(messages) - cut_at,
        )
        return messages[:cut_at]
    return messages


def _parse_tool_args(tc: Any) -> dict[str, Any]:
    """安全解析 tool call 的 JSON 参数。"""
    try:
        if tc.function and tc.function.arguments:
            return json.loads(tc.function.arguments)
    except json.JSONDecodeError:
        logger.warning("无法解析 tool call 参数")
    return {}


def _truncate(s: str, n: int) -> str:
    """Truncate string safely (respects multi-byte chars)."""
    s = s.replace("\n", " ").replace("\r", "").strip()
    if len(s) <= n:
        return s
    # Truncate at the last complete char before position n
    truncated = s[:n]
    # Remove any incomplete UTF-8 byte at the end
    while truncated:
        try:
            truncated.encode("utf-8")
            break
        except UnicodeEncodeError:
            truncated = truncated[:-1]
    return truncated + "..."


# ── 上下文压缩 ─────────────────────────────────────────


async def _compact_context(
    messages: list[Message],
    llm: "LLMClient",
    system_prompt: str = "",
    keep_last: int = 8,
) -> list[Message]:
    """压缩消息历史以适配 LLM 上下文窗口。

    策略:
      1. 保留 system message（第 0 条）
      2. 保留最近 keep_last 条消息（安全窗口）
      3. 中间部分 → 发送给 LLM 做一句话摘要
      4. 用一个合成 SystemMessage 替代被移除的消息段

    Args:
        messages: 完整的消息列表
        llm: 用于生成摘要的 LLM 客户端
        system_prompt: 原始 system prompt（保留不变）
        keep_last: 保留最近多少条消息

    Returns:
        压缩后的消息列表（新列表，不修改原列表）
    """
    if len(messages) <= keep_last + 4:
        return messages  # 太少，不需要压缩

    # Partition: 所有前导 system 消息保留（主 system prompt + brain prompt 等），最后 keep_last 条保留
    head_sys: list[Message] = []
    first_non_sys = 0
    for m in messages:
        if m.role == "system":
            head_sys.append(m)
            first_non_sys += 1
        else:
            break

    # 切分点必须落在「轮次边界」（user 消息），否则会把 assistant(tool_calls) 拆进 middle、
    # 对应的 tool 结果留在 recent，产生孤儿 tool 消息 → LLM 400
    # (Messages with role 'tool' must be a response to a preceding message with 'tool_calls')
    split = len(messages) - keep_last
    while split > first_non_sys and messages[split].role not in ("user", "system"):
        split -= 1

    middle = messages[first_non_sys:split]
    recent = messages[split:]

    if len(middle) <= 2:
        return messages  # 中间没有足够内容可摘要

    # 构建摘要请求
    middle_text = _messages_to_text(middle)
    summary_prompt = (
        "Summarize this conversation segment in 2-3 sentences (in the same language as the user). "
        "Focus on: decisions made, files touched, key findings, unresolved questions.\n\n"
        f"{middle_text}"
    )

    try:
        summary_msgs: list[dict[str, Any]] = [
            {"role": "user", "content": summary_prompt},
        ]
        response = await llm.chat(summary_msgs, tools=None, temperature=0.0, max_tokens=256)
        summary_text = (response.content or "").strip()
    except Exception as exc:
        logger.warning("上下文摘要生成失败: %s，使用简单截断", exc)
        summary_text = f"[{len(middle)} 条被截断的消息]"

    # 组装新消息列表 — 保留所有前导 system 消息（主 prompt + brain prompt + skill prompt 等）
    compacted: list[Message] = []
    compacted.extend(head_sys)

    compacted.append(SystemMessage(
        content=f"[对话摘要 — 以下为之前 {len(middle)} 条消息的摘要]\n{summary_text}\n[摘要结束]"
    ))
    compacted.extend(recent)

    logger.info(
        "上下文压缩完成: %d → %d 条消息",
        len(messages), len(compacted),
    )
    return compacted


def _messages_to_text(messages: list[Message]) -> str:
    """Convert a Message slice to compact text for summarization."""
    lines: list[str] = []
    for m in messages:
        role = m.role
        if m.content:
            text = m.content[:400]  # Truncate per-message to avoid huge summary input
            lines.append(f"[{role}] {text}")
        if m.tool_calls:
            for tc in m.tool_calls:
                fn = tc.function.name if tc.function else "?"
                args = (tc.function.arguments if tc.function else "{}")[:100]
                lines.append(f"[{role} → {fn}({args})]")
    return "\n".join(lines)



def _count_context_tokens(messages: list[Message], system_prompt: str = "") -> int:
    """估算当前上下文的总 token 数（粗略：4 char ≈ 1 token）。

    包括 system prompt + 所有 messages，每个 message 用 4 char/token 近似。
    这个估算偏低（不计算 tool call schema JSON），但对窗口管理足够。
    """
    total = len(system_prompt) // 4 if system_prompt else 0
    for m in messages:
        if m.content:
            total += len(m.content) // 4
        if m.tool_calls:
            for tc in m.tool_calls:
                total += len(tc.function.arguments) // 4 if tc.function else 0
    return total


def _to_model_toolcalls(tc_list: Optional[list[Any]]) -> Optional[list[ToolCall]]:
    """将 LLM 客户端的 ToolCall 转为 core.models.ToolCall。"""
    if tc_list is None:
        return None
    result = []
    for tc in tc_list:
        fn = tc.function
        from mai_agent.core.models import FunctionCall as ModelFunctionCall
        result.append(ToolCall(
            id=tc.id,
            function=ModelFunctionCall(
                name=fn.name if fn else "",
                arguments=fn.arguments if fn else "{}",
            ),
        ))
    return result
