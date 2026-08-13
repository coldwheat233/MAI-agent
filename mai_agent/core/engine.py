"""QueryEngine — 会话生命周期管理。

对应 Claude Code 的 QueryEngine.ts。

管理:
  - 多轮对话状态（messages）
  - 文件状态缓存
  - 子 Agent 追踪
  - 权限模式切换
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from mai_agent.core.loop import agent_loop, AgentLoopConfig, StepProgress, StepProgress
from mai_agent.llm.client import LLMClient
from mai_agent.core.models import Message, PermissionMode, UserMessage, AssistantMessage
from mai_agent.tools.base import RunContext
from mai_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    """引擎配置 — 对应 Claude Code 的 QueryEngineConfig。"""
    llm_api_key: str
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-v4-pro"
    tools: Optional[ToolRegistry] = None
    system_prompt: Optional[str] = None
    permission_mode: str = "auto"
    ask_permission: Any = None  # async fn(tool_name, args) -> bool
    max_turns: int = 50
    cwd: str = "."
    # 沙箱
    sandbox_mode: str = "off"  # off | default | strict
    sandbox_writable: str = ""  # 逗号分隔可写路径白名单
    # 四脑
    brain_type: str = ""  # 空=无 | dev_explorer | dev_validator | knowledge_explorer | deploy_planner


class AgentEngine:
    """Agent 引擎 — 管理一次完整会话。

    Claude Code 对应物: QueryEngine class.

    Usage::

        engine = AgentEngine(config)
        engine.start()

        answer, messages = await engine.submit("帮我查看这个项目")
        print(answer)

        answer2, messages = await engine.submit("继续，添加单元测试")
        # messages 包含上一轮的完整历史，上下文不丢失
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self._llm = LLMClient(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
        )
        self._tools = config.tools or ToolRegistry()
        self._messages: list[Message] = []
        # 并行"流式占位 assistant"——agent_loop 内部的 assistant 还没 commit 到
        # self._messages 之前，先把流出的 text / tool 增量攒在这里；存盘时拼到
        # _messages 末尾一起落盘（仅作崩溃恢复用，正常返回时由 all_messages 覆盖）。
        # 不喂给 agent_loop，所以不会在 _messages 里留下空 assistant。
        self._streaming: AssistantMessage | None = None
        self._run_context = RunContext(
            cwd=config.cwd,
            permission_mode=config.permission_mode,
            active_brain=config.brain_type,
            session_state=self._init_session_state(),
        )
        self._loop_config = AgentLoopConfig(
            max_turns=config.max_turns,
            permission_mode=config.permission_mode,
            ask_permission=config.ask_permission,
        )
        if config.system_prompt:
            self._loop_config.system_prompt = config.system_prompt

        self._session_id = str(uuid.uuid4())[:8]
        self._turn_count = 0
        self._bg_tasks: set[asyncio.Task] = set()

        # Session stats
        self._start_time = 0.0
        self._tools_called: list[str] = []  # tool names per call
        self._files_touched: set[str] = set()

        # Structured logger (JSON-lines, async writer)
        self._slog = None
        # 四脑协调器状态
        self._coordinator_ctx = None  # CoordinatorContext | None

    def _init_session_state(self) -> dict[str, Any]:
        """初始化会话级共享状态（含沙箱策略、项目根）。"""
        state: dict[str, Any] = {"project_root": self.config.cwd}
        # 沙箱策略
        sandbox_mode = getattr(self.config, "sandbox_mode", "off")
        if sandbox_mode and sandbox_mode != "off":
            from mai_agent.sandbox.policy import default_policy, strict_policy
            writable = getattr(self.config, "sandbox_writable", "") or ""
            paths = [p.strip() for p in writable.split(",") if p.strip()]
            if sandbox_mode == "strict":
                policy = strict_policy(writable_paths=paths)
            else:
                policy = default_policy(writable_paths=paths)
            state["sandbox"] = policy

            # 同步沙箱策略到 hook 层（供 Write/Edit 工具使用）
            from mai_agent.hooks.builtins import set_sandbox_hook_state
            set_sandbox_hook_state(policy, self.config.cwd)
        else:
            # 清除 hook 层沙箱状态
            from mai_agent.hooks.builtins import set_sandbox_hook_state
            set_sandbox_hook_state(None, self.config.cwd)
        return state

    def start(self) -> None:
        """初始化会话。重置所有状态。"""
        from mai_agent.services.memory import reset_state
        reset_state()

        self._messages = []
        self._run_context = RunContext(
            cwd=self.config.cwd,
            permission_mode=self.config.permission_mode,
            active_brain=self.config.brain_type,
            session_state=self._init_session_state(),
        )
        self._turn_count = 0
        self._start_time = time.monotonic()
        self._tools_called = []
        self._files_touched = set()

        # Start structured logger
        from mai_agent.services.structured_logger import get_logger
        self._slog = get_logger(self._session_id, self.config.cwd)

        # 初始化线段树记忆索引
        try:
            from mai_agent.services.memory_tags import init_tree
            init_tree(self.config.cwd)
        except Exception:
            pass

        # 加载 Plugin
        try:
            from mai_agent.plugins.loader import load_plugins
            load_plugins(self.config.cwd)
        except Exception:
            pass

        # 加载 MCP 服务器（不依赖运行中的事件循环——无循环时登记为 pending，
        # 由 start_mcp() 在异步上下文中启动；有循环时保持原行为立即调度）
        try:
            from mai_agent.tools.mcp_tools import load_mcp_config, start_mcp_servers
            mcp_configs = load_mcp_config(self.config.cwd)
            if mcp_configs:
                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(start_mcp_servers(mcp_configs))
                    self._bg_tasks.add(task)
                except RuntimeError:
                    self._pending_mcp_configs = mcp_configs
        except Exception:
            pass

        logger.info("会话 %s 已启动", self._session_id)

    async def start_mcp(self) -> None:
        """在异步上下文中启动登记为 pending 的 MCP 服务器（幂等）。"""
        configs = getattr(self, "_pending_mcp_configs", None)
        if not configs:
            return
        self._pending_mcp_configs = None
        from mai_agent.tools.mcp_tools import start_mcp_servers
        task = asyncio.create_task(start_mcp_servers(configs))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def submit(self, user_input: str, on_progress=None) -> tuple[str, list[Message]]:
        """提交一次用户输入，返回 (最终回答, 完整消息历史)。

        多次调用 submit() 会累积消息历史，实现跨轮次对话。
        """
        self._turn_count += 1
        context = self._run_context

        # ── 预先 commit user 消息 ─────────────────────────────
        # 必须在 agent_loop 之前把 UserMessage 落到 self._messages：
        # agent_loop 内部是 "messages.append(UserMessage) → 调 LLM 流式 → ... → return"，
        # 如果在 LLM 流式阶段被 cancel（CancelledError），self._messages 从未被赋值，
        # cancel 分支 save_session 就会把"缺了这一条 user"的版本写盘——
        # 表现就是"重发/再发时最近一条对话被抹除"。
        # 先 append 进 self._messages，agent_loop 用 _skip_user_append 跳过重复 append，
        # 这样 cancel 时 engine.messages 一定包含本轮的 user，save 不会再抹。
        self._messages.append(UserMessage(content=user_input))
        # 流式占位：让 checkpoint / 断连 save 能拿到正在流出的 assistant 内容
        self._streaming = AssistantMessage(content="", tool_calls=[])

        # Rebuild system prompt fresh every submit (picks up latest cwd)
        # 含 git subprocess + 文件扫描，放线程池避免阻塞事件循环
        await asyncio.to_thread(self._refresh_system_prompt)

        # ── 四脑自动协调 ──
        # 由 permission_mode 驱动，auto 模式下每次提交都跑，
        # plan 只跑 explore、manual 跳过。
        # 仅 "hi" 一类单短词消息直接跳过（不浪费 token）。
        _mode = self._run_context.permission_mode
        if _mode in ("auto"):
            keepalive_task: asyncio.Task | None = None
            try:
                from mai_agent.brains.coordinator import (
                    Coordinator, CoordinatorContext, BrainState,
                )
                async def _coord_keepalive():
                    while True:
                        await asyncio.sleep(15)
                        if on_progress:
                            await on_progress(StepProgress(
                                step=0, max_steps=self._loop_config.max_turns,
                                event="text", text=".",
                            ))

                if on_progress:
                    await on_progress(StepProgress(
                        step=0, max_steps=self._loop_config.max_turns,
                        event="text",
                        text="[四脑协调中——auto 模式自动分析任务...]\n",
                    ))
                    keepalive_task = asyncio.create_task(_coord_keepalive())

                if self._coordinator_ctx is None:
                    self._coordinator_ctx = CoordinatorContext(state=BrainState.IDLE)
                coord = Coordinator(
                    registry=self._tools,
                    context=context,
                    model=self.config.llm_model,
                    api_key=self.config.llm_api_key,
                    base_url=self.config.llm_base_url or "https://api.deepseek.com/v1",
                )
                coord.state = self._coordinator_ctx

                if self.config.permission_mode == "plan":
                    # plan: 只 explore，生成 checklist 但不验证
                    checklist = await coord.explore(user_input)
                    self._coordinator_ctx = coord.state
                    self._loop_config.system_prompt += (
                        f"\n\n[四脑 explore — {coord.state.status_bar()}]\n"
                        f"Checklist: {checklist}\n"
                        "[plan 模式 — 不执行写操作。]"
                    )
                else:
                    # auto: 完整 explore→validate 循环
                    result = await coord.run_full_cycle(user_input)
                    self._coordinator_ctx = coord.state
                    self._loop_config.system_prompt += (
                        f"\n\n[四脑协调结果 — {self._coordinator_ctx.status_bar()}]\n"
                        f"{result}\n"
                        "[协调结束 — 请基于以上分析和 checklist 继续执行任务。]"
                    )
                logger.info(
                    "Coordinator done: state=%s iteration=%d mode=%s",
                    self._coordinator_ctx.state.value,
                    self._coordinator_ctx.iteration,
                    self.config.permission_mode,
                )
            except Exception as exc:
                logger.warning("Coordinator 运行失败，跳过: %s", exc)
            finally:
                if keepalive_task is not None:
                    keepalive_task.cancel()
        elif self._coordinator_ctx is not None and self._coordinator_ctx.state.value != "idle":
            # 短消息 / manual 模式：不跑新周期，但保留上一轮协调状态
            self._loop_config.system_prompt += (
                "\n\n" + self._coordinator_ctx.status_bar()
            )

        # Start logger background writer if needed
        if self._slog and not self._slog._running:
            await self._slog.start()

        final_answer, all_messages = await agent_loop(
            user_input=user_input,
            llm=self._llm,
            registry=self._tools,
            context=context,
            config=self._loop_config,
            initial_messages=self._messages,
            on_progress=on_progress,
            _skip_user_append=True,
        )

        # 更新持久化消息历史
        self._messages = all_messages
        # 真实 assistant 已被 all_messages 覆盖，清掉并行占位
        self._streaming = None

        # Track tool names for stats + log
        for m in all_messages:
            if m.tool_calls:
                for tc in m.tool_calls:
                    name = tc.function.name if tc.function else "tool"
                    self._tools_called.append(name)
                    if self._slog:
                        self._slog.log("tool_call", {
                            "tool": name,
                            "turn": self._turn_count,
                        })
            # 记录工具错误
            if m.role == "tool" and m.content and m.content.startswith("[ERROR]"):
                if self._slog:
                    self._slog.log("tool_error", {
                        "turn": self._turn_count,
                        "error": m.content[:200],
                    })

        # Log turn completion
        if self._slog:
            self._slog.log("turn_converge", {
                "turn": self._turn_count,
                "tools_called": len(self._tools_called),
                "messages": len(all_messages),
                "answer_preview": final_answer[:200] if final_answer else "",
            })

        # Memory extraction — dual threshold check (token delta + tool calls + safe window)
        from mai_agent.services.memory import should_extract
        if should_extract(all_messages):
            task = asyncio.create_task(self._extract_memory())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

        # 概念检测 — 从用户输入中提取技术概念（后台，不阻塞）
        task2 = asyncio.create_task(self._detect_concepts(user_input))
        self._bg_tasks.add(task2)
        task2.add_done_callback(self._bg_tasks.discard)

        logger.info(
            "会话 %s 第 %d 轮完成 — messages: %d",
            self._session_id,
            self._turn_count,
            len(self._messages),
        )

        return final_answer, self._messages

    def _refresh_system_prompt(self) -> None:
        """重建 system prompt（同步，含 git/文件 I/O——调用方负责放线程池）。"""
        from mai_agent.context import build_system_prompt, get_system_context, get_user_context
        get_system_context.cache_clear()
        get_user_context.cache_clear()
        # Keep the original base prompt (first line, before any injected context)
        base = self._loop_config.system_prompt.split('当前日期:')[0].strip() if self._loop_config.system_prompt else ""
        if not base:
            base = self._loop_config.system_prompt
        self._loop_config.system_prompt = build_system_prompt(
            base, project_root=self.config.cwd,
        )

    async def _extract_memory(self) -> None:
        """后台提取会话记忆（不阻塞主循环）。"""
        try:
            from mai_agent.services.memory import extract_and_persist
            await extract_and_persist(
                messages=self._messages,
                project_root=self.config.cwd,
                api_key=self.config.llm_api_key,
                base_url=self.config.llm_base_url or "https://api.deepseek.com/v1",
                model=self.config.llm_model,
            )
        except Exception as exc:
            logger.warning("记忆提取失败: %s", exc)

    async def _detect_concepts(self, text: str) -> None:
        """后台检测用户输入中的技术概念，中/高复杂度自动入学习队列。"""
        try:
            from mai_agent.knowledge.vector_store import KnowledgeStore
            from mai_agent.knowledge.concept_detector import ConceptDetector
            from mai_agent.knowledge.learning_queue import list_items, add_item

            store = KnowledgeStore(knowledge_dir=self.config.cwd + "/.mai/knowledge")
            detector = ConceptDetector(
                knowledge_store=store,
                api_key=self.config.llm_api_key,
                base_url=self.config.llm_base_url or "https://api.deepseek.com/v1",
                model=self.config.llm_model,
            )
            extracted = await detector.extract(text)

            # 已有概念去重（不区分大小写）
            try:
                existing = {i["concept"].lower() for i in list_items(self.config.cwd)}
            except Exception:
                existing = set()

            for c in extracted:
                if c.complexity in ("medium", "high"):
                    logger.info("检测到概念: %s (复杂度: %s)", c.term, c.complexity)
                    if c.term.lower() not in existing:
                        try:
                            add_item(
                                concept=c.term,
                                context=c.context,
                                priority=c.complexity,
                                base_dir=self.config.cwd,
                            )
                            logger.info("已加入学习队列: %s", c.term)
                            existing.add(c.term.lower())
                        except Exception:
                            pass
        except Exception as exc:
            logger.debug("概念检测失败: %s", exc)

    async def stop(self) -> None:
        """Gracefully stop the engine — flush logs, cancel background tasks."""
        for t in list(self._bg_tasks):
            t.cancel()
        # 停止 MCP 服务器
        try:
            from mai_agent.tools.mcp_tools import stop_all_mcp
            await stop_all_mcp()
        except Exception:
            pass
        if self._slog:
            self._slog.log("session_end", {"turns": self._turn_count, "tools_total": len(self._tools_called)})
            await self._slog.stop()

    def set_mode(self, mode: str) -> None:
        """切换权限模式: auto | manual | plan"""
        self._run_context.permission_mode = mode
        self._loop_config.permission_mode = mode
        logger.info("会话 %s 权限模式切换为: %s", self._session_id, mode)

    def set_brain(self, brain_type: str) -> None:
        """激活或关闭脑模式。

        Args:
            brain_type: 脑名（dev_explorer/dev_validator/...）或 "" 关闭。
        """
        valid = {"", "dev_explorer", "dev_validator", "knowledge_explorer", "deploy_planner"}
        if brain_type not in valid:
            raise ValueError(f"未知 brain: {brain_type}。有效: {', '.join(v for v in valid if v)}")
        self._run_context.active_brain = brain_type
        self.config.brain_type = brain_type
        # 初始化/清除协调器状态
        if brain_type:
            from mai_agent.brains.coordinator import CoordinatorContext, BrainState
            self._coordinator_ctx = CoordinatorContext(state=BrainState.IDLE)
        else:
            self._coordinator_ctx = None
        logger.info("会话 %s 脑切换为: %s", self._session_id, brain_type or "off")

    @property
    def coordinator_status(self) -> str:
        """获取当前协调器状态栏文本（用于注入 system prompt 或前端展示）。"""
        if self._coordinator_ctx:
            return self._coordinator_ctx.status_bar()
        return ""

    def snapshot_messages(self) -> list[Message]:
        """存盘用的快照：self._messages +（若存在）流式占位 _streaming。

        agent_loop 还没 return 时，真实 assistant 还没 commit 到 _messages，
        _streaming 替它"占位"承接流出来的内容；存盘时拼到末尾一起落盘——
        崩溃/关窗口也能保住正在流的那一段文字。正常返回时 _streaming 会被清掉。"""
        if self._streaming is not None:
            return [*self._messages, self._streaming]
        return list(self._messages)

    @property
    def messages(self) -> list[Message]:
        return self._messages

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def pending_tasks(self) -> int:
        """Number of background tasks still running."""
        return len([t for t in self._bg_tasks if not t.done()])

    @property
    def total_tool_calls(self) -> int:
        return len(self._tools_called)

    @property
    def elapsed(self) -> float:
        """Elapsed session time in seconds."""
        if self._start_time == 0:
            return 0.0
        return time.monotonic() - self._start_time

    @property
    def stats(self) -> dict[str, Any]:
        """Session statistics for recap."""
        from collections import Counter
        tool_counts = Counter(self._tools_called)
        return {
            "session_id": self._session_id,
            "turns": self._turn_count,
            "tool_calls": len(self._tools_called),
            "tool_breakdown": dict(tool_counts),
            "duration_sec": self.elapsed,
            "messages": len(self._messages),
            "bg_tasks_pending": self.pending_tasks,
        }


def _estimate_tokens(messages: list[Message]) -> int:
    """简单 token 估算：每 4 字符 ≈ 1 token。"""
    total = 0
    for m in messages:
        if m.content:
            total += len(m.content) // 4
    return total
