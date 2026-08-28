# Generated Module Map（自动生成，勿手改 — 运行 extract_module_map.py 重新生成）

扫描时间: 2026-08-28T21:21:38
模块总数: 71 | 总行数: 14277

## 模块摘要

### __init__.py
`MAI-agent — 以 Claude Code 架构为地基的桌面端个人开发 Agent 平台。`

行数: 6

---

### brains/__init__.py
`四脑系统入口`

行数: 1

---

### brains/coordinator.py
`Coordinator — 四脑调度状态机。`

类:
- `BrainState` — (无文档)
- `CoordinatorContext` — Mutable state tracked across the brain lifecycle.
- `Coordinator` — Orchestrates the four-brain lifecycle.

函数:
- `parse_verdict()` — Parse a brain's output to determine the verdict.
- `status_bar()` — Generate a structured status summary for injection into LLM context.
- `start()` — (无文档)

依赖: `mai_agent.brains.definitions`, `mai_agent.core.models`, `mai_agent.llm.client`, `mai_agent.tools.base`, `mai_agent.tools.orchestration`, `mai_agent.tools.registry`

行数: 407

---

### brains/definitions.py
`四脑的 AgentDefinition — 每个脑有不同的 System Prompt 和工具白名单。`

依赖: `mai_agent.core.models`

行数: 166

---

### cli.py
`CLI entry point for `mai` command — installed via pyproject.toml [project.scripts].`

函数:
- `main()` — MAI-agent — Personal Development Agent Platform

依赖: `mai_agent.config`, `mai_agent.context`, `mai_agent.core.engine`, `mai_agent.core.loop`, `mai_agent.server`, `mai_agent.session`, `mai_agent.skills.loader`, `mai_agent.tools`, `mai_agent.tools.bash`, `mai_agent.tools.mcp_tools`

行数: 609

---

### config.py
`全局配置 — 对应 Claude Code 的 config 体系 + settings.json。`

类:
- `Config` — (无文档)

函数:
- `get_config()` — 全局配置单例
- `validate()` — (无文档)

行数: 64

---

### context.py
`上下文注入 — 对应 Claude Code 的 context.ts。`

函数:
- `get_system_context()` — 每会话缓存的系统上下文。
- `get_user_context()` — 每会话缓存的用户/项目上下文。
- `get_brain_context()` — 脑模式专用上下文注入。
- `build_system_prompt()` — 组装完整的 system prompt — 三层上下文合并。

依赖: `mai_agent.services.memory`, `mai_agent.services.memory_tags`, `mai_agent.skills.loader`

行数: 183

---

### core/__init__.py
`核心运行时模块`

行数: 1

---

### core/engine.py
`QueryEngine — 会话生命周期管理。`

类:
- `EngineConfig` — 引擎配置 — 对应 Claude Code 的 QueryEngineConfig。
- `AgentEngine` — Agent 引擎 — 管理一次完整会话。

函数:
- `start()` — 初始化会话。重置所有状态。
- `set_mode()` — 切换权限模式: auto | manual | plan
- `switch_model()` — 热切换模型——不重建引擎、不丢上下文（对齐 DSH adapter replace）。
- `set_brain()` — 激活或关闭脑模式。
- `coordinator_status()` — 获取当前协调器状态栏文本（用于注入 system prompt 或前端展示）。
- `snapshot_messages()` — 存盘用的快照：self._messages +（若存在）流式占位 _streaming。

依赖: `mai_agent.brains.coordinator`, `mai_agent.context`, `mai_agent.core.loop`, `mai_agent.core.models`, `mai_agent.knowledge.concept_detector`, `mai_agent.knowledge.learning_queue`, `mai_agent.knowledge.vector_store`, `mai_agent.llm.client`, `mai_agent.llm.providers`, `mai_agent.plugins.loader`

行数: 520

---

### core/loop.py
`Agent 核心循环 — 对应 Claude Code 的 query.ts。`

类:
- `StepProgress` — Emitted by agent_loop for CLI visibility.
- `AgentLoopConfig` — Agent 循环配置

函数:
- `messages_to_openai()` — 将内部 Message 列表转为 OpenAI API 格式。
- `strip_incomplete_tool_calls()` — 清洗不完整的 tool_calls 序列。

依赖: `mai_agent.brains.definitions`, `mai_agent.core.models`, `mai_agent.hooks.executor`, `mai_agent.hooks.gate`, `mai_agent.hooks.types`, `mai_agent.llm.client`, `mai_agent.services.trace`, `mai_agent.tools.base`, `mai_agent.tools.orchestration`, `mai_agent.tools.registry`

行数: 699

---

### core/models.py
`消息、工具调用、会话状态的核心类型定义。`

类:
- `MessageRole` — (无文档)
- `Message` — (无文档)
- `SystemMessage` — (无文档)
- `UserMessage` — (无文档)
- `AssistantMessage` — (无文档)
- `ToolResultMessage` — (无文档)
- `FunctionCall` — (无文档)
- `ToolCall` — (无文档)

行数: 122

---

### db.py
`SQLite 持久层 — 替代旧的 JSON 文件 + 浏览器 localStorage。`

函数:
- `get_conn()` — 进程内单例连接。
- `transaction()` — with transaction(): ... — 自动 BEGIN / COMMIT / ROLLBACK（跨线程串行化）。
- `init_db()` — 建表 + 一次性 JSON 迁移。
- `register_workspace()` — 注册一个 workspace 路径（用户级，已存在则刷新 last_used）。
- `unregister_workspace()` — 从全局索引移除（不会删磁盘上的项目目录）。
- `list_workspaces()` — (无文档)

依赖: `mai_agent.core.loop`, `mai_agent.core.models`

行数: 570

---

### hooks/__init__.py
`Hook 系统入口`

依赖: `mai_agent.hooks`, `mai_agent.hooks.executor`, `mai_agent.hooks.gate`, `mai_agent.hooks.types`

行数: 24

---

### hooks/builtins.py
`内置 Hook — 系统级 PreToolUse / PostToolUse hooks。`

依赖: `mai_agent.hooks.types`, `mai_agent.services.structured_logger`

行数: 128

---

### hooks/executor.py
`Hook 执行器 — 匹配 + 执行 Hook 链。`

依赖: `mai_agent.hooks.types`

行数: 73

---

### hooks/gate.py
`权限门控 — 对应 Claude Code 的 hooks/useCanUseTool.ts。`

依赖: `mai_agent.core.models`, `mai_agent.hooks.executor`, `mai_agent.hooks.types`

行数: 79

---

### hooks/types.py
`Hook 类型定义 — 对应 Claude Code 的 types/hooks.ts。`

类:
- `HookEvent` — Hook 事件类型 — 对应 Claude Code 的 HookEvent。
- `PreToolUseResult` — PreToolUse hook 的返回结果。
- `HookMatcher` — Hook 匹配器 — 决定哪个 hook 对哪个事件响应。
- `HookRegistry` — 全局 Hook 注册表。

函数:
- `matches()` — (无文档)
- `register()` — 注册一个 Hook，返回撤销函数（disposer）。
- `match()` — 查找匹配 event + tool_name 的所有 Hook，按 priority 排序。
- `clear()` — (无文档)
- `dispose()` — 撤销此 hook（幂等）。

行数: 158

---

### knowledge/__init__.py
`Knowledge engine — hybrid search + concept boundary detection.`

依赖: `mai_agent.knowledge.concept_detector`, `mai_agent.knowledge.embedding`, `mai_agent.knowledge.vector_store`

行数: 37

---

### knowledge/concept_detector.py
`Concept boundary detector — LLM-powered unknown concept identification.`

类:
- `DetectedConcept` — (无文档)
- `ConceptDetector` — LLM-driven concept boundary detection.

依赖: `mai_agent.knowledge.vector_store`, `mai_agent.llm.client`

行数: 175

---

### knowledge/embedding.py
`Embedding abstraction — swappable backends.`

类:
- `EmbeddingBackend` — Abstract embedding backend.
- `LocalTransformer` — Local sentence-transformers model — zero API cost, privacy-safe.
- `APIEmbedding` — DeepSeek/OpenAI-compatible embedding API.

函数:
- `create_embedding()` — Create an embedding backend.
- `dim()` — Embedding dimension.
- `name()` — Backend identifier.
- `dim()` — (无文档)
- `name()` — (无文档)
- `dim()` — (无文档)

行数: 162

---

### knowledge/learning_queue.py
`Learning Queue — tracks unknown concepts for later study & Feishu sync.`

类:
- `LearningItem` — (无文档)

函数:
- `list_items()` — List all learning queue items, newest first.
- `add_item()` — Add a new concept to the learning queue.
- `update_item()` — Update a learning queue item. Set status='learned' to mark as learned.
- `delete_item()` — Remove an item from the queue.
- `get_stats()` — Get queue statistics.

行数: 108

---

### knowledge/vector_store.py
`Vector store — Chroma-backed with hybrid search (BM25 + vector).`

类:
- `_BM25Index` — Minimal BM25 keyword search (no external dependency).
- `_NoOpEmbeddingFunction` — No-op embedding — 向量由外部 embedding 生成，chroma 只存储。
- `KnowledgeStore` — Hybrid search over persisted knowledge.

函数:
- `get_store()` — 按 persist_dir 缓存的 KnowledgeStore（保持 BM25 索引跨调用持久）。
- `add()` — (无文档)
- `remove()` — (无文档)
- `search()` — (无文档)
- `name()` — (无文档)
- `tokenize()` — (无文档)

行数: 326

---

### llm/__init__.py
`LLM 模块入口`

依赖: `mai_agent.llm.client`

行数: 5

---

### llm/client.py
`LLM 客户端 — OpenAI 兼容协议。`

类:
- `ToolCall` — LLM 返回的单个 tool call。
- `FunctionCall` — (无文档)
- `Usage` — 单次 LLM 调用的 token 使用量。
- `LLMResponse` — LLM 单次调用返回结构。
- `LLMClient` — 轻量 LLM 客户端 — OpenAI 兼容协议，带指数退避重试。

函数:
- `set_fallback_providers()` — 设置备用 provider 列表（自动容灾用）。
- `reconfigure()` — 热切换 provider/model——重建底层 client，保留对象身份与重试逻辑。

行数: 433

---

### llm/providers.py
`LLM Provider 注册表 — 对齐 DeepSeek Harness 的 provider 抽象（轻量自研版）。`

类:
- `ProviderConfig` — 单个 provider 的运行时配置。

函数:
- `upsert_provider()` — 创建或更新一个 provider（自定义或覆盖内置的 key/models）。写持久化文件。
- `delete_provider()` — 删除自定义 provider（内置 provider 的覆盖记录也删，回到默认）。
- `list_providers()` — 列出所有 provider（内置 + 自定义 + 持久化覆盖）。
- `resolve_provider()` — 按名字解析 provider；不存在返回 None。
- `current_provider()` — 当前激活的 provider（LLM_PROVIDER 指定，默认 deepseek）。
- `save_models()` — 把模型目录持久化到 providers.json（发现结果或手动添加后调用）。

依赖: `mai_agent.config`

行数: 308

---

### plugins/__init__.py
`Plugin 双轨扩展系统 — 对应 Claude Code 的 plugins/ 目录。`

依赖: `mai_agent.plugins.loader`

行数: 19

---

### plugins/loader.py
`Plugin 加载器 — 扫描 .mai/plugins/ 目录，解析 manifest，注册工具/hook/skill。`

类:
- `PluginManifest` — Plugin 清单。
- `PluginRegistry` — 已加载的 plugin 注册表。

函数:
- `load_plugins()` — 扫描 .mai/plugins/ 并加载所有启用的 plugin。
- `get_plugin_registry()` — (无文档)
- `reload_plugins()` — (无文档)
- `add()` — (无文档)
- `get()` — (无文档)
- `all()` — (无文档)

行数: 187

---

### sandbox/__init__.py
`沙箱策略 — 对 Bash 命令的受限执行控制。`

依赖: `mai_agent.sandbox.policy`

行数: 32

---

### sandbox/policy.py
`沙箱策略实现 — 命令静态审查 + 路径约束。`

类:
- `SandboxDecision` — (无文档)
- `SandboxViolation` — 一条违规记录。
- `SandboxPolicy` — 沙箱策略配置。

函数:
- `default_policy()` — 默认沙箱：拦截高危命令 + 路径越界写，不禁网络。
- `strict_policy()` — 严格沙箱：仅白名单命令 + 禁网络 + 路径约束。
- `validate_command()` — 便捷入口：用给定策略审查命令。
- `check_file_write()` — 检查 Write/Edit 的目标路径是否在沙箱允许范围内。
- `active()` — (无文档)
- `validate()` — 审查命令，返回 (决策, 违规列表)。

行数: 286

---

### server.py
`MAI-agent Desktop Server — FastAPI + WebSocket 实时流式。`

函数:
- `init_engine()` — 初始化引擎（不设全局——由 _init_engine_async 注册到 _engines）。

依赖: `mai_agent`, `mai_agent.config`, `mai_agent.context`, `mai_agent.core.engine`, `mai_agent.core.loop`, `mai_agent.core.models`, `mai_agent.knowledge.learning_queue`, `mai_agent.llm.providers`, `mai_agent.services.feishu`, `mai_agent.services.memory_tags`

行数: 1142

---

### services/__init__.py
`服务层模块`

行数: 1

---

### services/feishu.py
`Feishu/Lark API client — tenant token auth, wiki docs, search.`

类:
- `FeishuClient` — Minimal Feishu client — get token, search docs, read/write docs.

行数: 451

---

### services/mcp_client.py
`MCP (Model Context Protocol) Client — JSON-RPC over stdio.`

类:
- `MCPServerConfig` — MCP 服务器配置 — 对应 .mcp.json 中的一个条目。
- `MCPToolDef` — MCP 工具定义（从 tools/list 返回）。
- `MCPClient` — MCP JSON-RPC 客户端 — 管理一个 MCP 服务器进程。
- `MCPError` — MCP 协议错误。

行数: 292

---

### services/memory.py
`Session Memory — upgraded to Claude Code standards.`

函数:
- `set_config()` — Override default thresholds. e.g. set_config(min_tokens_to_init=5000).
- `reset_state()` — Reset all module state (for new session).
- `should_extract()` — Determine if memory extraction should trigger.
- `memory_path()` — (无文档)
- `load_memory()` — (无文档)
- `memory_context_for_prompt()` — Build a context block from memory for injection into system prompt.

依赖: `mai_agent.core.models`, `mai_agent.llm.client`

行数: 416

---

### services/memory_segtree.py
`H2Mem: Memory Segment Tree — 按时间排序的记忆线段树。`

类:
- `SegNode` — 线段树节点。叶子节点 left=None and right=None。
- `MemorySegTree` — 记忆线段树。

函数:
- `is_leaf()` — (无文档)
- `width()` — (无文档)
- `to_dict()` — 序列化为 JSON 兼容 dict。
- `from_dict()` — 从 JSON dict 反序列化。
- `build()` — 自底向上构建完整二叉树（含虚拟叶子）。O(n)。
- `insert()` — 插入一张卡片。

依赖: `mai_agent.services.memory_tags`

行数: 744

---

### services/memory_tags.py
`Tagged Memory 系统 — 对应 Claude Code 的记忆模型。`

类:
- `TaggedMemory` — 一条标签化记忆卡片。

函数:
- `init_tree()` — 初始化某工作区的记忆线段树（尝试加载或从零构建，按工作区缓存）。
- `get_tree()` — 获取指定工作区的 MemorySegTree 实例（None 表示不可用）。
- `memory_dir()` — (无文档)
- `index_path()` — (无文档)
- `tag_index_path()` — (无文档)
- `load_memory_by_name()` — 按 name 加载一条记忆卡片。

依赖: `mai_agent.services.memory_segtree`

行数: 474

---

### services/structured_logger.py
`Structured Logging Service — JSON-lines, AI-determined granularity, async queue.`

类:
- `StructuredLogger` — JSON-lines structured logger with async background writer.

函数:
- `get_logger()` — Get or create a structured logger for a session.
- `log()` — Enqueue a log entry. Non-blocking — never blocks the agent loop.
- `path()` — (无文档)
- `count()` — (无文档)

行数: 222

---

### services/trace.py
`Trace 采集服务 — span 级轨迹记录（对齐 OpenTelemetry GenAI 语义约定的轻量自研版）。`

类:
- `TraceRecorder` — 会话级 trace 收集器：异步队列 → jsonl 落盘，不阻塞 agent 循环。

函数:
- `estimate_cost()` — 按模型单价估算单次调用的美元成本。
- `make_span()` — 构造一个 span 事件 dict（jsonl 一行）。
- `get_recorder()` — 获取（或创建）会话级 recorder。
- `load_trace_file()` — 从磁盘读回一次会话的完整 trace（历史回放用）。
- `list_trace_sessions()` — 列出项目下所有有 trace 的会话（含统计摘要）。
- `summarize_trace()` — 把 span 列表压成会话级摘要（前端聚合条用）。

行数: 301

---

### session.py
`会话持久化 — SQLite 薄壳。`

函数:
- `save_session()` — 持久化会话消息。返回 DB 文件路径（兼容旧返回 Path 的调用方）。
- `load_session()` — (无文档)
- `get_session_workspace()` — (无文档)
- `list_sessions()` — (无文档)
- `list_workspaces()` — 列出所有已知 workspace。base_root 参数在 SQLite 模型下被忽略（DB 是用户级全局）。
- `delete_session()` — (无文档)

依赖: `mai_agent`, `mai_agent.core.models`

行数: 64

---

### skills/__init__.py
`Skill 系统 — 对应 Claude Code 的 skills/ 目录。`

依赖: `mai_agent.skills.loader`

行数: 26

---

### skills/loader.py
`Skill 加载器 — 扫描 skill 目录、解析 frontmatter、构建注册表。`

类:
- `Skill` — 一个已加载的 skill。
- `SkillRegistry` — Skill 注册表 — 按名查找、列出可见 skill。

函数:
- `load_skills()` — 扫描项目级 + 用户级 skill 目录，构建注册表。
- `get_skill_registry()` — 获取（并缓存）skill 注册表。首次调用时扫描磁盘。
- `reload_skills()` — 强制重新扫描磁盘（用于运行时新增 skill 后刷新）。
- `listing_line()` — 注入 system prompt 的一行描述。对应 available-skills 列表。
- `add()` — (无文档)
- `get()` — (无文档)

行数: 236

---

### tasks/__init__.py
`后台任务系统入口`

行数: 1

---

### tools/__init__.py
`工具基础设施入口`

依赖: `mai_agent.tools`, `mai_agent.tools.base`, `mai_agent.tools.orchestration`, `mai_agent.tools.registry`

行数: 41

---

### tools/agent_tool.py
`子Agent孵化工具 — 对应 Claude Code 的 AgentTool。`

类:
- `AgentToolInput` — (无文档)
- `AgentTool` — 孵化子 Agent 以执行特定脑的任务。

依赖: `mai_agent.brains.definitions`, `mai_agent.config`, `mai_agent.llm.client`, `mai_agent.tools.base`, `mai_agent.tools.orchestration`, `mai_agent.tools.registry`

行数: 143

---

### tools/ask_user_question.py
`AskUserQuestion — 对应 Claude Code 的 AskUserQuestionTool。`

类:
- `Question` — (无文档)
- `AskUserQuestionInput` — (无文档)
- `AskUserQuestionTool` — 模型调用此工具向用户提问。

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 95

---

### tools/base.py
`工具基类 — 对应 Claude Code 的 Tool.ts。`

类:
- `ToolInput` — 工具参数的基类。每个具体工具继承此类定义自己的参数 schema。
- `ToolResult` — 工具执行结果
- `RunContext` — 工具执行上下文 — 对应 Claude Code 的 ToolUseContext。
- `Tool` — 工具基类 — 所有工具必须继承此类。

函数:
- `is_aborted()` — (无文档)
- `write_targets()` — 声明此工具将写入的资源目标（路径/键），用于并发冲突判定。
- `to_openai_schema()` — 将工具转换为 OpenAI function calling 格式。

行数: 164

---

### tools/bash.py
`Shell 执行工具 — 对应 Claude Code 的 BashTool。`

类:
- `BashInput` — (无文档)
- `BashTool` — 在子进程中执行 shell 命令。

依赖: `mai_agent.sandbox.policy`, `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 124

---

### tools/cron_tools.py
`Cron 系列工具 — 对应 Claude Code 的 CronCreate/CronDelete/CronList。`

类:
- `CronCreateInput` — (无文档)
- `CronCreateTool` — (无文档)
- `CronDeleteInput` — (无文档)
- `CronDeleteTool` — (无文档)
- `CronListInput` — (无文档)
- `CronListTool` — (无文档)

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 130

---

### tools/deploy_tools.py
`Deploy tools — 部署管道：Plan → Check → Run → Rollback。`

类:
- `DeployPlanInput` — (无文档)
- `DeployPlanTool` — 生成部署计划——分析项目并生成步骤化的部署清单。
- `DeployCheckInput` — (无文档)
- `DeployCheckTool` — 部署前检查——测试是否通过？git 是否干净？
- `DeployRunInput` — (无文档)
- `DeployRunTool` — 执行一个部署步骤。
- `DeployRollbackInput` — (无文档)
- `DeployRollbackTool` — 回滚一个已完成的部署步骤。

依赖: `mai_agent.sandbox.policy`, `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 341

---

### tools/feishu_tools.py
`Feishu/Lark knowledge base tools.`

类:
- `FeishuSearchInput` — (无文档)
- `FeishuSearchTool` — (无文档)
- `FeishuReadInput` — (无文档)
- `FeishuReadTool` — (无文档)
- `FeishuWriteInput` — (无文档)
- `FeishuWriteTool` — (无文档)
- `FeishuListInput` — (无文档)
- `FeishuListTool` — (无文档)

依赖: `mai_agent.config`, `mai_agent.services.feishu`, `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 288

---

### tools/file_edit.py
`精确字符串替换工具 — 对应 Claude Code 的 FileEditTool。`

类:
- `FileEditInput` — (无文档)
- `FileEditTool` — 精确字符串替换。

函数:
- `write_targets()` — 声明写目标：file_path。多个 Edit/Write 写不同文件可并发。

依赖: `mai_agent.sandbox.policy`, `mai_agent.tools.base`, `mai_agent.tools.registry`, `mai_agent.tools.snapshots`, `mai_agent.tools.utils`

行数: 101

---

### tools/file_read.py
`文件读取工具 — 对应 Claude Code 的 FileReadTool。`

类:
- `FileReadInput` — (无文档)
- `FileReadTool` — 读取文件内容。

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`, `mai_agent.tools.utils`

行数: 62

---

### tools/file_write.py
`文件覆写工具 — 对应 Claude Code 的 FileWriteTool。`

类:
- `FileWriteInput` — (无文档)
- `FileWriteTool` — 创建或覆写文件。

函数:
- `write_targets()` — 声明写目标：file_path。多个 Write/Edit 写不同文件可并发。

依赖: `mai_agent.sandbox.policy`, `mai_agent.tools.base`, `mai_agent.tools.registry`, `mai_agent.tools.snapshots`, `mai_agent.tools.utils`

行数: 71

---

### tools/git_tools.py
`Git tools — status, diff, commit, log.`

类:
- `GitStatusInput` — No parameters needed — shows status of current repo.
- `GitStatusTool` — (无文档)
- `GitDiffInput` — (无文档)
- `GitDiffTool` — (无文档)
- `GitCommitInput` — (无文档)
- `GitCommitTool` — Git commit — in manual mode, the permission gate shows diff first.
- `GitLogInput` — (无文档)
- `GitLogTool` — (无文档)

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 304

---

### tools/glob.py
`文件模式匹配工具 — 对应 Claude Code 的 GlobTool。`

类:
- `GlobInput` — (无文档)
- `GlobTool` — 按 glob 模式匹配文件路径。

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 50

---

### tools/grep.py
`内容搜索工具 — 对应 Claude Code 的 GrepTool。`

类:
- `GrepInput` — (无文档)
- `GrepTool` — 基于 ripgrep 的内容搜索。

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 145

---

### tools/mcp_tools.py
`MCP 工具适配器 — 将外部 MCP 服务器的工具暴露给 MAI-agent。`

类:
- `McpToolInput` — 代理工具的输入：列出 or 调用。
- `McpTool` — MCP 代理工具 — 列表 + 调用的统一入口（懒加载）。

函数:
- `load_mcp_config()` — 从 .mcp.json 加载 MCP 服务器配置。

依赖: `mai_agent.services.mcp_client`, `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 181

---

### tools/memory_tools.py
`记忆工具 — 标签化长期记忆卡片的增删查。`

类:
- `MemoryWriteInput` — (无文档)
- `MemoryWriteTool` — 创建或更新一条标签化长期记忆卡片。
- `MemorySearchInput` — (无文档)
- `MemorySearchTool` — 检索长期记忆卡片：按全文/标签/类型。
- `MemoryReadInput` — (无文档)
- `MemoryReadTool` — 读取单条记忆卡片全文，可选解析 wiki-link 关联。
- `MemoryListInput` — (无文档)
- `MemoryListTool` — 列出所有长期记忆卡片索引 + 所有标签。

依赖: `mai_agent.services`, `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 221

---

### tools/notebook_edit.py
`NotebookEdit — 对应 Claude Code 的 NotebookEditTool。`

类:
- `NotebookEditInput` — (无文档)
- `NotebookEditTool` — 编辑 Jupyter notebook 单元格。

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`, `mai_agent.tools.utils`

行数: 107

---

### tools/orchestration.py
`工具编排 — 对应 Claude Code 的 services/tools/toolOrchestration.ts。`

类:
- `ToolUseBlock` — LLM 返回的单个工具调用。
- `ToolExecutionResult` — (无文档)

函数:
- `partition_by_safety()` — 将工具调用分区为三组。

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 170

---

### tools/registry.py
`工具注册表 — 对应 Claude Code 的 tools.ts。`

类:
- `ToolRegistry` — 全局工具注册表。

函数:
- `register()` — 注册一个工具。
- `get()` — 按名查找工具，未找到抛出 KeyError。
- `has()` — (无文档)
- `get_visible()` — 返回指定模式下可见的工具列表。
- `to_openai_schemas()` — 转为 OpenAI function calling 的 tools 参数。
- `names()` — (无文档)

依赖: `mai_agent.tools.base`

行数: 83

---

### tools/send_message.py
`SendMessage — 对应 Claude Code 的 SendMessageTool。`

类:
- `SendMessageInput` — (无文档)
- `SendMessageTool` — Agent 间消息传递。

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 43

---

### tools/skill_tool.py
`Skill 工具 — 对应 Claude Code 的 SkillTool。`

类:
- `SkillInput` — (无文档)
- `SkillTool` — 激活一个已加载的 skill，将其指令注入当前回合上下文。

依赖: `mai_agent.skills.loader`, `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 72

---

### tools/snapshots.py
`File snapshots — save file state before edits for undo.`

函数:
- `snapshot_dir()` — (无文档)
- `save_snapshot()` — Save a copy of a file before editing. Returns snapshot ID.
- `restore_snapshot()` — Restore a file from snapshot. Returns the file path or None.
- `list_snapshots()` — List all snapshots.

行数: 75

---

### tools/task_tools.py
`Task 系列工具 — 对应 Claude Code 的 TaskCreate/TaskUpdate/TaskGet/TaskList/TaskOutput/TaskStop。`

类:
- `TaskCreateInput` — (无文档)
- `TaskCreateTool` — (无文档)
- `TaskUpdateInput` — (无文档)
- `TaskUpdateTool` — (无文档)
- `TaskListInput` — (无文档)
- `TaskListTool` — (无文档)
- `TaskGetInput` — (无文档)
- `TaskGetTool` — (无文档)

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 221

---

### tools/todo_write.py
`TodoWrite — 对应 Claude Code 的 TodoWriteTool。`

类:
- `TodoWriteInput` — (无文档)
- `TodoWriteTool` — (无文档)

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 41

---

### tools/utils.py
`Tool utility functions — shared across all tools.`

函数:
- `resolve_path()` — Resolve a path string to an absolute Path, handling Windows quirks.

行数: 44

---

### tools/web_fetch.py
`网页抓取工具 — 对应 Claude Code 的 WebFetchTool。`

类:
- `WebFetchInput` — (无文档)
- `_TextExtractor` — Strip HTML tags, keep text content and links.
- `WebFetchTool` — 抓取网页内容并提取文本。

函数:
- `handle_starttag()` — (无文档)
- `handle_endtag()` — (无文档)
- `handle_data()` — (无文档)
- `get_text()` — (无文档)

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 165

---

### tools/web_search.py
`网页搜索工具 — 对应 Claude Code 的 WebSearchTool。`

类:
- `WebSearchInput` — (无文档)
- `WebSearchTool` — 网页搜索（DuckDuckGo 免费 API，无需 Key）

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 86

---

### tools/workflow_tool.py
`Workflow Tool — 并行多 Agent 协作。`

类:
- `WorkflowInput` — (无文档)
- `WorkflowTool` — 并行执行多个子 Agent 任务并汇总结果。

依赖: `mai_agent.config`, `mai_agent.core.loop`, `mai_agent.llm.client`, `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 156

---

### tools/worktree_tools.py
`工作区隔离工具 — 对应 Claude Code 的 EnterWorktree / ExitWorktree。`

类:
- `EnterWorktreeInput` — (无文档)
- `EnterWorktreeTool` — 创建/进入 git worktree，切换会话工作目录到隔离副本。
- `ExitWorktreeInput` — (无文档)
- `ExitWorktreeTool` — 退出当前 worktree，返回原工作目录。可选保留或移除。
- `ListWorktreesInput` — (无文档)
- `ListWorktreesTool` — 列出当前仓库所有 git worktree。

依赖: `mai_agent.tools.base`, `mai_agent.tools.registry`

行数: 295

---
