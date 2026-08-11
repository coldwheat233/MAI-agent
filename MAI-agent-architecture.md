# MAI-agent 架构地图 v0.3（2026-08-11 更新）

> 写给自己看的——vibe-coding 出来的东西到底长什么样，数据怎么流的。

---

## 1. 一句话定义

**MAI-agent** 是 Claude Code 的 Python 复刻。不依赖任何 Agent 框架（LangChain / CrewAI / OpenAI Agents），从 LLM Client 到工具编排全部手写。Electron + React 桌面端，WebSocket 流式交互。

```
~12,000 行 Python（49 tools, 122 tests）
~4,700 行 TypeScript（11 Zustand stores）
DeepSeek v4-pro · FastAPI + WebSocket · Electron 33 + React 18
```

---

## 2. 顶层文件地图

```
mai_agent/
├── core/
│   ├── loop.py          # ★ agent_loop — 思考-行动-观察 主循环（~580行）
│   ├── engine.py         # ★ AgentEngine — 会话生命周期 + 四脑协调（~480行）
│   └── models.py         # 消息模型 (Message / ToolCall / PermissionMode)
├── server.py             # ★ FastAPI + WebSocket + 每工作区引擎隔离（~780行）
├── context.py            # ★ 三层上下文注入 (system / user / brain)
├── session.py            # ★ Session 持久化 + 工作区元数据 + 全局索引
├── config.py             # pydantic-settings 全局配置
├── cli.py                # CLI + REPL 入口
├── tools/                # 49 tools（含 registry, orchestration）
├── hooks/                # Hook 权限门控（PreToolUse deny / ask / allow）
├── llm/client.py         # LLM 客户端（流式 + 非流式 + 重试）
├── services/
│   ├── memory.py         # SESSION_MEMORY.md 自动会话摘要
│   ├── memory_tags.py    # 标签化记忆卡片（.mai/memory/*.md）
│   ├── memory_segtree.py # ★ 记忆线段树 H2Mem（~750行）
│   ├── mcp_client.py     # MCP 协议客户端（子进程管理）
│   └── feishu.py         # 飞书文档同步
├── knowledge/
│   ├── concept_detector.py  # LLM 概念提取器
│   ├── learning_queue.py    # 学习队列（.mai/knowledge/learning_queue.json）
│   ├── vector_store.py      # ChromaDB 向量存储（可选依赖）
│   └── embedding.py
├── brains/               # 四脑协调器 — Coordinator 状态机 + Agent 定义
├── skills/loader.py      # Skill 扫描与注册（.mai/skills/）
├── plugins/loader.py     # Plugin 热加载（.mai/plugins/）
├── sandbox/policy.py     # 沙箱文件系统策略
└── static/               # 前端打包产物（prod），dev 走 vite:5173

desktop/
├── src/main/
│   ├── index.ts          # Electron 主进程入口
│   ├── backend.ts        # Python 后端生命周期管理
│   ├── window.ts         # BrowserWindow — dev→vite:5173, prod→FastAPI static/
│   └── tray.ts, menu.ts
└── src/renderer/
    ├── App.tsx           # 入口组件：WS 连接 + 消息提交 + 追加式重发
    ├── stores/           # 11 Zustand stores
    ├── components/       # 侧边栏 / 聊天区 / 输入区 / 面板 / 其他工作区会话
    ├── hooks/            # 自动滚动 / 自动补全 / 键盘快捷键 / 命令菜单
    ├── lib/              # API 客户端 / WS 消息分发 / 常量 / Markdown 渲染
    └── types/            # TypeScript 类型定义
```

---

## 3. 一次完整对话的数据流

```
用户输入
  ↓
InputArea.tsx → onSubmit → addUserMessage(前端气泡)
  → send({type:'submit', text})
  ↓
WebSocket /ws → server.py websocket_endpoint
  → 若该工作区有在途 submit → _cancel_submit_for(key, timeout=1.0)
  → engine = _get_engine()  ← 每工作区独立引擎，懒创建
  → asyncio.create_task(_run_submit(...))
  ↓
_run_submit → engine.submit(text, on_progress=progress_callback)
  ↓
engine.submit:
  1. _refresh_system_prompt() (线程池)
     → build_system_prompt = base + 日期 + cwd + git status
       + CLAUDE.md + memory_context + tagged_memory_context(segtree)
       + skill listing + brain context
  2. ── 四脑自动协调（auto 模式）──
     → Coordinator.run_full_cycle(user_input)
         → explore (dev_explorer 子Agent, 最多12轮)
         → validate (dev_validator 子Agent, 最多12轮)
         → BLOCKED? → 循环回 explore（最多3次）
         → 结果注入 self._loop_config.system_prompt
     → 协调期间每15s发 keepalive "." 防 WS 超时
  3. agent_loop(user_input, llm, registry, context, config, messages)
  ↓
agent_loop (思考-行动-观察):
  for step 1..max_turns:
    ├─ 中断检查 context.is_aborted()
    ├─ 上下文压缩 (80%阈值 → _compact_context)
    ├─ llm.chat_stream(messages, tools) → 流式产出 + 流中中断检查
    ├─ append assistant message
    ├─ if no tool_calls → converge → return  ← 终止
    ├─ 权限门控: can_use_tool(tool_name, input, mode)
    │   ├─ PreToolUse hooks (deny/ask/allow)
    │   ├─ plan 模式只读白名单
    │   └─ auto 全通过
    ├─ partition_by_safety → 并发组(Semaphore 10) + 串行组
    ├─ run_tools → 工具执行 → on_progress 事件
    └─ append tool_result messages → 回到 loop 顶部
  ↓
engine.submit 返回后:
  → save_session(session_id, messages, cwd)  (线程池落盘)
  → WS send_event("done") → chatStore.completeStream
  → _detect_concepts(text) → LLM提取概念 → learning_queue.json（自动）
  → should_extract → _extract_memory → LLM提取记忆 → .mai/memory/*.md（自动）
```

---

## 4. 每工作区引擎隔离（2026-08-11 修）

```
修复前：单全局 _engine。切换工作区 → engine.stop() + cancel submit + 重建 → 卡 30-60s
修复后：
  _engines: dict[str, AgentEngine]  ← 一工作区一引擎，独立运行
  _submit_tasks: dict[str, asyncio.Task]  ← 一工作区一任务
  _config.project_root  ← 指向当前"活跃"工作区

切换工作区：
  1. _config.project_root = new_cwd  ← 只改指针，瞬时
  2. 旧引擎继续跑它的 coordinator / submit
  3. 新引擎懒创建：第一次 submit 时 _get_engine() 创建
  4. _get_engine(cwd): 查 _engines 缓存 → 命中返回 / 未命中 asyncio.to_thread(init_engine)
```

---

## 5. 49 Tools 全景

### 5.1 按功能分组

| 组 | 数量 | 工具 |
|----|------|------|
| 文件 | 6 | Read, Write, Edit, Glob, Grep, NotebookEdit |
| Shell | 1 | Bash |
| Git | 8 | Status, Diff, Commit, Log, Push, Pull, Clone, Remote |
| 记忆 | 5 | MemoryWrite, MemoryRead, MemorySearch, MemoryList, MemoryDelete |
| 飞书 | 4 | FeishuSearch, Read, Write, List |
| 任务 | 6 | TaskCreate, Update, List, Get, Output, Stop |
| 子Agent | 3 | Agent, SendMessage, AskUserQuestion |
| 编排 | 2 | Workflow, Skill |
| 定时 | 3 | CronCreate, Delete, List |
| 工作区 | 3 | EnterWorktree, ExitWorktree, ListWorktrees |
| 部署 | 5 | DeployPlan, Check, Run, Rollback, List（⚠ 骨架级） |
| Web | 2 | WebSearch, WebFetch |
| Todo | 1 | TodoWrite |
| MCP | 动态 | .mcp.json 配置的子进程工具 |

### 5.2 并发分区

`partition_by_safety` 按 `tool.is_concurrency_safe` 分区：

- **并发组（23）**：Read, Grep, Glob, GitStatus, GitDiff, GitLog, Memory*, TaskList, TaskGet, TaskOutput, WebSearch, WebFetch, Feishu*, CronList, DeployList, Skill, AskUserQuestion —— `asyncio.gather + Semaphore(10)`
- **串行组（26）**：Write, Edit, Bash, GitCommit, GitPush, GitPull, GitClone, NotebookEdit, Agent, TaskCreate, TaskUpdate, TaskStop, SendMessage, CronCreate, CronDelete, Workflow, Worktree*, Deploy*, MCP* —— 顺序执行，未知工具默认串行

---

## 6. 权限门控：Hook 链 + 三模式

```
PreToolUse Hook 链
  ├─ deny → 直接拒绝（所有模式生效）
  ├─ ask  → auto/plan 下自动拒绝，manual 下弹给用户确认
  └─ (通过) → 进入模式层

模式层
  ├─ plan → 只允许只读白名单（Read/Grep/Glob/MemoryRead/...共16个）
  └─ auto/manual → 所有通过则放行
```

Hook 通过 `@hook_registry.register(event, tool_pattern, name)` 注册回调。

---

## 7. 停止机制（2026-08-11 修）

```
修复前：单协程顺序处理 WS 消息——await engine.submit() 期间 stop 无人接收
修复后：

用户点 stop
  → send({type:'stop'})
  ↓
WS 接收 (Task-based——receive 循环不受 submit 阻塞)
  → abort_signal.set()              ← 协作式 abort（逐 token 检查）
  → _cancel_current_submit(timeout=3.0)  ← 硬取消 Task
  ↓
agent_loop 捕获 CancelledError:
  → text_buf 刷出
  → 未落盘的 partial text 补进 messages
  → return (partial + "(已被用户停止)", messages)
  ↓
engine.submit 正常返回 → save_session → done 事件 → 前端定型

实测 stop→done 延迟 0.02s。部分回答零丢失。
```

---

## 8. 记忆系统三层架构

### 8.1 SESSION_MEMORY.md（自动会话摘要）

- `should_extract(messages)` — 双阈值判断
- `extract_and_persist` — 调 LLM 生成摘要 → 追加
- `memory_context_for_prompt` — 取最近 3000 字符注入 system prompt

### 8.2 标签化记忆卡片

- `.mai/memory/<name>.md` — YAML frontmatter（name/description/type/tags）
- `MEMORY.md` — 自动维护的索引
- `tags.json` — 自动维护的倒排索引
- `[[wiki-link]]` — 记忆间交叉引用

### 8.3 H2Mem 记忆线段树（~750行）

在按时间升序的 `cards[]` 数组上建立完全二分段树（补齐到 2 的幂）。

```
         [0,8) "根摘要 ~50 tokens"
       /           \
     [0,4)         [4,8)
    /    \         /    \
  [0,2) [2,4)   [4,6) [6,8)
   / \    / \     / \    / \
  [0][1][2][3]  [4][5][6][7虚拟]  ← 叶子：单张卡片（topics + date）
```

- **叶子**：card_count=1, topics=卡片 tags, earliest/latest_date
- **内部节点**：LLM 摘要 + topics 并集 + 日期范围
- **懒标记 dirty**：插入/删除只走路径更新，不触发全树重建。Batch Shifts 缓存最近 100 次插入偏移
- **标签检索** `query_by_tag(tag)`：topics 剪枝，O(log n + k)
- **时间区间** `query_by_daterange(start, end)`：earliest/latest_date 双重剪枝
- **Prompt 注入** `tagged_memory_context`：优先用 `_tree.root.summary`（~50 tokens）

---

## 9. 桌面端 11 Zustand Stores

| Store | 职责 |
|-------|------|
| **chatStore** | 消息列表、流式状态、追加文本、工具卡片、收敛/错误 |
| **wsStore** | WebSocket 连接生命周期、重连退避、send() |
| **workspaceStore** | 当前工作区、切换/添加/移除、setCwd、localStorage 持久 |
| **sessionStore** | 会话列表（支持 ?workspace=）、加载/删除/新建 |
| **settingsStore** | 模型选择、权限模式、沙箱、脑类型、飞书配置 |
| **toolStore** | 工具清单（ready 事件写入） |
| **skillStore** | Skill 清单 |
| **memoryStore** | 记忆面板（tag 过滤、全文搜索） |
| **gitStore** | Git 状态（30s 轮询） |
| **uiStore** | 侧边栏折叠、面板开关、设置弹窗 |

### WS 消息分发

```
ready              → settingsStore.setModel + toolStore.setTools
thinking           → chatStore.startThinking
text               → chatStore.appendText
tool_start         → chatStore.startTool
tool_result        → chatStore.finishTool
converge           → chatStore.converge
done               → chatStore.completeStream + sessionStore.fetchSessions
error              → chatStore.handleError
status             → console.log
workspace_switched → workspaceStore.setCwd + sessionStore.fetchSessions
```

### Dev 与 Prod 加载差异（2026-08-11 修）

```
修复前：window.ts 写死 loadURL('http://localhost:8765') → 始终加载 stale static/ 打包产物
修复后：
  Electron Main —— dev:  loadURL('http://localhost:5173')  ← vite HMR
  │                    prod: loadURL('http://localhost:8765') ← FastAPI static/
  │              vite.config 代理: /ws → 8765 (ws:true), /api → 8765
  └─ Python 后端 —— uvicorn.run(app, host='127.0.0.1', port=8765)
```

---

## 10. Session 持久化与工作区定位（2026-08-11 修）

### 存储结构

```
<project>/.mai/
├── workspaces/
│   └── <slug>/               # D__PY_PROJ_MAI-agent
│       ├── sessions/
│       │   └── <session_id>.json
│       └── workspace.json     # {"path": "D:/PY/PROJ/MAI-agent"} ← 元数据
├── memory/
│   ├── MEMORY.md, tags.json, segments.json, *.md
├── knowledge/
│   └── learning_queue.json
└── logs/

~/.mai/workspaces.json         # 全局索引（所有工作区，不随项目切换漂移）
```

### 工作区定位路径解析优先级

```
1. workspace.json 元数据文件（准确，新数据走这条）
2. session 文件的 workspace 字段（兼容旧数据）
3. 修正后的 slug 解码兜底（先拆 __ 再替 _）
```

- `load_session` 跨工作区查找：当前 → 旧路径 → 全局索引 → `_all_workspace_dirs`
- `/api/sessions?workspace=X` 支持查询任意工作区 session
- 新建会话立即落盘（`api_restart`）

---

## 11. 四脑自动协调（2026-08-11 接入）

```
修复前：Coordinator 状态机已定义但从未接入 agent_loop，纯手动选脑
修复后：auto 模式下每次 submit 自动触发

engine.submit:
  if permission_mode == "auto":
    Coordinator.run_full_cycle(user_input)
      ├─ Phase 1: explore → dev_explorer 子Agent（最多12轮）
      ├─ Phase 2: validate → dev_validator 子Agent（最多12轮）
      └─ BLOCKED? → 循环回 explore（最多3次）
    → 结果注入 system prompt

  plan 模式：只跑 explore，生成 checklist 不验证
  manual 模式：不跑协调
```

| 脑 | 角色 | 允许工具 | 状态 |
|---|---|---|---|
| dev_explorer | 需求拆解、生成 checklist | 6（读+搜+写） | prompt 注入 + 自动调度 ✓ |
| dev_validator | 验证 checklist、运行测试 | 5（读+搜+bash） | prompt 注入 + 自动调度 ✓ |
| knowledge_explorer | 识别未知概念 | 4（读+搜+memory） | prompt 注入，未自动调度 |
| deploy_planner | 部署计划 | 3（读+搜） | 空壳 |

---

## 12. MCP 协议集成

- **配置**：`.mcp.json` → `load_mcp_config`
- **通信**：子进程 stdin/stdout JSON-RPC
- **工具注册**：MCPToolWrapper(Tool)，`mcp__<server>__<tool>`
- **生命周期**：engine.start() 异步启动 → stop() 3s 超时 → kill
- **当前状态**：filesystem + sqlite 两个 server 配置 `enabled: false`

---

## 13. 上下文压缩

- 触发：`_count_context_tokens` 超 80% 阈值
- 策略：保留全部 system message + 最近 8 条 → 中间 LLM 摘要 → 合成 SystemMessage 替换
- 压缩率：60-80%

---

## 14. 概念检测 + 学习队列（2026-08-11 打通）

每次 submit 后后台触发：
1. LLM 提取技术概念（term + context + complexity）
2. 中/高复杂度 + 去重 → 自动 `add_item` 写入 `learning_queue.json`
3. 前端 Learning 面板：待学 / 已学 / 已同步

---

## 15. 已知限制（诚实清单）

| 项目 | 状态 |
|------|------|
| 四脑自动调度 | dev_explorer+dev_validator 已接入；knowledge_explorer 和 deploy_planner 未调度 |
| Coordinator 流式 | `_run_brain` 用非流式 llm.chat，子 Agent 无进度展示 |
| SegTree LLM 摘要 | `_merge_summaries_llm` 已实现但默认走模板拼接；未后台定时调度 |
| Deploy 工具 | 5 个全部骨架——接口完整，实际逻辑空 |
| MCP 服务器 | .mcp.json 配置存在但 enabled:false |
| 学习队列去重 | 按概念名精确匹配，未用 vector search 语义去重 |
| 测试 | 122 单元测试，0 集成测试（Coordinator/SegTree/MCP/WS 多轮均无覆盖） |
