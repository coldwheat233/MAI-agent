# MAI-agent v0.3

> 个人 AI 开发 Agent 平台 — Python 复刻 Claude Code 架构 + Electron/React 桌面端

```
~9,900 lines Python  |  49 tools  |  135 tests  |  DeepSeek v4-pro  |  asyncio + FastAPI + WebSocket
 Electron 33 + React 18 + Zustand 4.5 + Tailwind CSS 3  |  TypeScript 5.5 + Vite 5
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+ (桌面端)
- Git（可选，用于 Git 工具和工作区管理）

### 安装

```bash
# 后端依赖
pip install httpx click rich python-dotenv pydantic pydantic-settings openai fastapi "uvicorn[standard]"

# 可选：知识引擎
pip install chromadb sentence-transformers

# 开发/测试
pip install pytest pytest-asyncio

# 桌面端
cd desktop && npm install
```

### 配置

项目根目录 `.env`:

```env
LLM_API_KEY=sk-your-deepseek-key
LLM_MODEL=deepseek-v4-pro
LLM_BASE_URL=https://api.deepseek.com/v1

# 可选：飞书
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

### 启动

```bash
# 后端 API 服务器（含 WebSocket）
python -m mai_agent.cli --serve --port 8765

# 桌面端开发模式
cd desktop && npm run dev

# 桌面端构建
cd desktop && npm run build

# 打包 Windows 便携版
cd desktop && npm run package
```

### CLI 模式

```bash
python -m mai_agent.cli                      # 交互式 REPL
python -m mai_agent.cli --once "任务"        # 单次执行
python -m mai_agent.cli --plan               # 只读 Plan 模式
python -m mai_agent.cli --session my-id      # 指定会话
```

REPL 命令：
```
/help        帮助
/tools       列出全部 49 个工具
/mode auto|manual|plan  切换权限
/sessions    查看历史会话
/exit        退出（显示 recap）
Ctrl+C       两阶段退出（防误触）
```

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MAI-agent v0.3                              │
│                                                                     │
│  ┌─────────────────────┐         HTTP/WS          ┌──────────────┐ │
│  │   Electron Desktop  │ ◄──────────────────────► │  FastAPI     │ │
│  │                     │   REST + WebSocket       │  Server      │ │
│  │  ┌───────────────┐  │                          │              │ │
│  │  │ React 18 SPA  │  │                          │  ┌─────────┐ │ │
│  │  │ Zustand ×10   │  │                          │  │ Agent   │ │ │
│  │  │ Tailwind CSS  │  │                          │  │ Engine  │ │ │
│  │  └───────────────┘  │                          │  └────┬────┘ │ │
│  │                     │                          │       │      │ │
│  │  electron-vite      │                          │  ┌────▼────┐ │ │
│  │  + Vite 5           │                          │  │ agent   │ │ │
│  └─────────────────────┘                          │  │ _loop() │ │ │
│                                                    │  └────┬────┘ │ │
│                                                    │       │      │ │
│                                                    │  ┌────▼────┐ │ │
│                 ┌──────────────────────────────────┤  │ 49 tools│ │ │
│                 │                                  │  └─────────┘ │ │
│        ┌────────▼────────┐                         │              │ │
│        │  LLM Provider   │ ◄── HTTP ────────────── │              │ │
│        │  DeepSeek v4-pro│                         └──────────────┘ │
│        └─────────────────┘                                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 数据流（一次完整对话）

```
User Input (React InputArea)
  → wsStore.send({ type: "submit", text })
  → WebSocket /ws
  → FastAPI websocket_endpoint
  → engine.submit(text, on_progress=progress_callback)
     → agent_loop()
       ① messages_to_openai() → 转 API 格式
       ② llm.chat_stream() → 流式调用 DeepSeek
       ③ 解析 tool_calls → ToolUseBlock 列表
       ④ permission gate (manual 模式弹出 y/n/a)
       ⑤ run_tools() — 分区执行
          · Read/Grep/Glob/WebSearch → 并发 (semaphore=10)
          · Edit/Write/Bash/Agent → 串行
       ⑥ progress_callback() → WebSocket events
       ⑦ 结果追加 → 循环直到模型返回纯文本
     → WebSocket events 回流:
       { type: "thinking" }
       { type: "text", data: "..." }
       { type: "tool_start", tool: "Read", args: {...} }
       { type: "tool_result", tool: "Read", result: "..." }
       { type: "converge", answer: "...", tokens: 1234 }
  → createWSHandler() → 分发到 zustand stores
     → chatStore.addMessage(msg)
     → React re-render (ChatArea → AssistantMessage → ToolCard/MarkdownRenderer)
```

### 前端 React 组件树

```
App.tsx
├── Sidebar
│   ├── WorkspaceSelector          // 工作区切换
│   ├── SessionList                // 会话列表 + 搜索
│   │   └── SessionItem            // 单条会话条目
│   ├── SidebarIconBar             // 侧栏图标 (Memory/Git/Learning/Settings)
│   └── ContextMenu + ConfirmModal // 右键菜单 + 删除确认
├── ChatArea
│   ├── EmptyState                 // 空状态 (无会话时)
│   ├── UserMessage                // 用户消息 (可编辑)
│   └── AssistantMessage           // 助手消息
│       ├── MarkdownRenderer       // Markdown → JSX
│       │   └── CodeBlock          // 语法高亮代码块
│       ├── ToolCard               // 工具调用卡片 (可折叠)
│       ├── ThinkingIndicator      // 思考中动画
│       └── StreamingCursor        // 流式输出光标
├── InputArea
│   ├── InputTextarea              // 自适应文本输入
│   ├── Autocomplete               // @文件路径 /命令 自动补全
│   ├── CommandMenu                // /命令快捷键菜单
│   ├── SendButton                 // 发送/停止按钮
│   ├── MicButton                  // 语音输入 (预留)
│   ├── AttachButton               // 附件按钮 (预留)
│   └── ImagePasteHandler          // 图片粘贴处理
├── PanelContainer                 // 右侧面板容器
│   ├── MemoryPanel                // 记忆浏览器
│   ├── SkillsPanel                // Skill 列表
│   ├── GitPanel                   // Git 状态面板
│   └── LearningPanel              // 学习队列面板
├── StatusBar                      // 底部状态栏
│   └── ModelBadge                 // 当前模型标签
├── SettingsModal                  // 设置弹窗
├── ThemeToggle                    // 主题切换 (暗色/亮色/系统)
└── [Hooks]
    ├── useTheme                   // 主题应用
    ├── useKeyboard                // 全局快捷键
    ├── useAutoScroll              // 聊天区自动滚动
    ├── useAutocomplete            // 输入自动补全逻辑
    ├── useCommandMenu             // 命令菜单逻辑
    └── useImagePaste              // 图片粘贴逻辑
```

---

## 模块依赖图

### 后端 Python 模块依赖

```
mai_agent/
├── cli.py                # CLI 入口 (click + Rich)
├── config.py             # 配置管理 (pydantic-settings + .env)
├── context.py            # System prompt 构建
├── server.py             # FastAPI + WebSocket server
├── session.py            # 会话持久化
├── core/
│   ├── engine.py          # AgentEngine — 会话生命周期、权限、统计
│   ├── loop.py            # agent_loop — 流式循环、工具编排、收敛
│   └── models.py          # 数据模型 (Message, TokenUsage)
├── tools/
│   ├── base.py            # Tool 抽象基类 + Pydantic Schema
│   ├── registry.py        # ToolRegistry — 集中注册 + Feature Flag
│   ├── orchestration.py  # 并发/串行分区编排
│   ├── utils.py           # run_tools 运行时工具
│   └── *.py              # 49 个工具实现
├── hooks/
│   ├── gate.py            # PreToolUse allow/deny/ask 门控
│   ├── executor.py        # Hook 执行引擎
│   ├── types.py           # Hook 类型定义
│   └── builtins.py        # 内置 Hook
├── brains/
│   ├── coordinator.py     # 四脑子 Agent 定义与状态（按需孵化，状态机为历史遗留）
│   └── definitions.py    # 脑定义
├── knowledge/
│   ├── concept_detector.py # 概念边界检测
│   ├── embedding.py       # 向量嵌入
│   ├── vector_store.py    # Chroma 向量存储
│   └── learning_queue.py  # 学习队列
├── services/
│   ├── memory.py           # 会话记忆提取 (双重阈值 + 异步互斥)
│   ├── memory_segtree.py   # 分段树记忆索引
│   ├── memory_tags.py      # 记忆标签系统
│   ├── feishu.py           # 飞书 API (tenant_token, wiki, docs)
│   ├── mcp_client.py       # MCP 客户端
│   └── structured_logger.py # 结构化日志
├── llm/
│   └── client.py           # LLM 客户端 (OpenAI SDK)
├── skills/
│   └── loader.py           # Skill 加载器
├── sandbox/
│   └── policy.py           # 沙箱安全策略
├── plugins/
│   └── loader.py           # 插件加载器
└── tasks/
    └── __init__.py         # 任务管理

# 依赖关系 (简化箭头 = import):
# server.py → core/engine.py, core/loop.py, tools/registry.py, context.py
# core/engine.py → core/loop.py, tools/registry.py, hooks/gate.py
# core/loop.py → llm/client.py, tools/orchestration.py, brains/coordinator.py
# tools/*.py → tools/base.py (所有工具继承 Tool)
# services/memory.py → services/memory_tags.py
# knowledge/concept_detector.py → knowledge/embedding.py, knowledge/vector_store.py
```

### 前端 React 组件 → Zustand Store → API

```
Components                          Stores                  API / Transport
────────────────────────────────────────────────────────────────────────────
App.tsx ───────────────────┐
ChatArea ──────────────┐    │
  AssistantMessage ────┤    │     ┌─ useChatStore ──────► (WS events)
  UserMessage ─────────┤    │     ├─ useSessionStore ───► api.fetchSessions()
  EmptyState ────┐     │    │     ├─ useWorkspaceStore ─► api.fetchWorkspace()
Sidebar ─────────┤     │    │     ├─ useSettingsStore ──► api.fetchFeishuStatus()
  SessionList ───┤     │    │     ├─ useUIStore ──────── (local state only)
  WorkspaceSel ──┤     ├────┼─────├─ useToolStore ──────► api.fetchTools()
  SidebarIconBar─┘     │    │     ├─ useGitStore ───────► api.fetchGitStatus()
InputArea ─────────────┤    │     ├─ useMemoryStore ────► api.fetchMemories()
SettingsModal ─────────┤    │     ├─ useSkillStore ─────► api.fetchSkills()
StatusBar ─────────────┤    │     └─ useWSStore ────────► WebSocket /ws
  ModelBadge ──────────┘    │
PanelContainer ─────────────┘
  MemoryPanel ───► useMemoryStore
  SkillsPanel ───► useSkillStore
  GitPanel ──────► useGitStore, useWSStore
  LearningPanel─► (raw fetch /api/learning-queue)

lib/
  api.ts ─────── REST 客户端 (fetch 封装，27 个端点)
  ws.ts ──────── WebSocket 消息分发器 (createWSHandler)
  constants.ts ─ 默认值、模型列表、连接参数
  markdown.tsx ─ Markdown 渲染 + highlight.js 语法高亮
```

---

## API 参考

### Base URL

```
http://localhost:8765
```

### REST 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 根路由，返回 SPA index.html 或服务信息 |
| `GET` | `/api/stats` | 当前引擎统计 (tokens、turns、tool calls) |
| `GET` | `/api/sessions` | 列出当前工作区所有会话 |
| `GET` | `/api/sessions/search?q=` | 全文搜索所有工作区的会话内容 |
| `GET` | `/api/sessions/{session_id}` | 获取会话完整消息历史 |
| `POST` | `/api/sessions/{session_id}/load` | 加载历史会话到当前引擎 |
| `DELETE` | `/api/sessions/{session_id}` | 删除指定会话 |
| `GET` | `/api/tools` | 列出全部 49 个工具及其描述 |
| `GET` | `/api/skills` | 列出项目可用的 Skill |
| `GET` | `/api/memories` | 列出所有记忆条目和标签 |
| `POST` | `/api/mode` | 切换权限模式 `{ "mode": "auto" \| "manual" \| "plan" }` |
| `POST` | `/api/brain` | 切换脑模式 `{ "brain": "explorer" \| "validator" \| "knowledge" \| "deploy" }` |
| `POST` | `/api/sandbox` | 设置沙箱模式 `{ "mode": "off" \| "default" \| "strict" }` |
| `POST` | `/api/model` | 切换模型 `{ "model": "deepseek-v4-pro" }` 并热重启引擎 |
| `POST` | `/api/restart` | 重启引擎 (清空上下文) |
| `GET` | `/api/workspaces` | 列出所有已知工作区 |
| `GET` | `/api/workspace` | 当前工作区详情 (路径、会话数、工作区列表) |
| `POST` | `/api/workspace` | 切换工作区 `{ "cwd": "/path/to/project" }` 并重启引擎 |
| `GET` | `/api/git` | 当前工作区 Git 状态 (分支、改动、最近提交) |
| `GET` | `/api/browse?path=` | 浏览文件系统目录 (工作区选择器) |
| `GET` | `/api/coordinator` | 获取当前激活的脑状态 |
| `GET` | `/api/feishu/status` | 检查飞书配置状态 |
| `POST` | `/api/feishu/config` | 保存飞书配置到 .env `{ "app_id", "app_secret" }` |
| `GET` | `/api/learning-queue` | 列出待学习队列及统计 |
| `POST` | `/api/learning-queue` | 添加学习项 `{ "concept", "context", "priority" }` |
| `PUT` | `/api/learning-queue/{item_id}` | 更新学习项状态 `{ "status", "notes" }` (自动同步飞书) |
| `DELETE` | `/api/learning-queue/{item_id}` | 删除学习项 |

### WebSocket `/ws`

**Incoming 消息 (客户端 → 服务器):**

| type | 字段 | 说明 |
|------|------|------|
| `submit` | `text`, `mode?`, `brain?` | 提交用户消息，可选指定权限/脑模式 |
| `stop` | — | 中断当前 Agent 执行 |
| `undo` | — | 撤销最近一轮对话 |

**Outgoing 事件 (服务器 → 客户端):**

| type | 字段 | 说明 |
|------|------|------|
| `ready` | `session_id`, `mode`, `brain`, `sandbox`, `model`, `tools` | 连接建立，发送当前状态 |
| `thinking` | — | Agent 开始思考 |
| `text` | `data` | 流式文本片段 |
| `tool_start` | `tool`, `args` | 工具调用开始 |
| `tool_result` | `tool`, `result`, `error` | 工具调用结果 |
| `converge` | `answer`, `tokens`, `context_tokens`, `max_context` | 本轮收敛，返回最终回答 |
| `done` | `turn`, `tools_called`, `pending_tasks` | 本轮完成 |
| `error` | `message` | 错误信息 |
| `status` | `message` | 状态通知 (如 undo/stop 结果) |

---

## 功能清单

### 49 工具

| 类别 | 工具 | 说明 |
|------|------|------|
| 文件操作 | `FileRead`, `FileEdit`, `FileWrite` | 读/编辑/写文件；编辑支持精确字符串替换 |
| 文件操作 | `NotebookEdit` | Jupyter Notebook (.ipynb) 单元格编辑 |
| 搜索 | `Grep`, `Glob` | 正则内容搜索 + glob 文件匹配 |
| 命令 | `Bash` | Shell 命令执行 (带超时和沙箱) |
| Web | `WebSearch`, `WebFetch` | 网页搜索 + URL 内容抓取 |
| Agent 孵化 | `Agent` | 孵化子 Agent 处理独立任务 |
| 任务管理 | `TaskCreate/Update/Get/List/Output/Stop` | 6 个任务生命周期管理工具 |
| Git | `GitStatus/Log/Diff/Commit/Push/Pull/Clone/Remote` | 8 个 Git 操作工具 |
| Worktree | `EnterWorktree`, `ExitWorktree`, `ListWorktrees` | 3 个 Git worktree 隔离工具 |
| 部署 | `DeployCheck/List/Plan/Run/Rollback` | 5 个部署管理工具 |
| 飞书 | `FeishuSearch/Read/Write/List` | 4 个飞书知识库操作工具 |
| 记忆 | `MemoryWrite/Read/List/Search/Delete` | 5 个记忆管理工具 |
| 调度 | `CronCreate/Delete/List` | 3 个定时任务工具 |
| 其他 | `TodoWrite`, `SendMessage`, `AskUserQuestion`, `Skill`, `Workflow` | 任务清单、Agent 通信、用户询问、Skill 调用、工作流 |
| MCP | `MCPTool` | MCP 协议工具包装 |

### 四脑（按需孵化的子 Agent）

四个脑是预定义的子 Agent 定义（`brains/definitions.py`），主 Agent 在需要时通过 `Agent` 工具**按需孵化**，
不再有强制 explore→validate 前置协调器——意图识别交给模型的 tool-call 自然决定，避免前置分类器的重复劳动与上下文膨胀。

- **dev_explorer**（探索者）: 需求拆解、生成测试清单
- **dev_validator**（验证者）: 运行测试、验证逻辑闭合
- **knowledge_explorer**（知识探索）: 识别未知概念、复杂度评估
- **deploy_planner**（部署规划）: 部署方案规划

每个脑有独立的 System Prompt + 工具白名单（`AgentDefinition.allowed_tools`）。

### Skill 系统

类似 Claude Code 的 Slash Commands，将项目特定的工作流打包为可复用 Skill。支持 Markdown frontmatter 定义 (name/description/whenToUse)，存储在项目 `.claude/skills/` 目录。

### 沙箱

三层安全模式：`off` (无限制) / `default` (仅当前项目目录可写) / `strict` (完全只读)。Bash 执行前预检路径，拒绝访问沙箱外路径。

### 工作区

多项目隔离，每个工作区独立维护会话列表和 Git 状态。支持浏览文件系统选择工作区目录。

### Git 集成

实时显示分支、未提交变更、最近 5 条提交。所有 Git 操作通过工具暴露给 Agent。

### 飞书集成

飞书知识库读写，tenant_token 认证。支持：搜索知识库、读取文档、创建/更新文档、列出知识库结构。学习队列完成项可自动同步为飞书文档。

### 记忆系统（三层：流水摘要 + 线段树索引 + 标签卡片）

不是单一 SESSION_MEMORY.md，是三层独立子系统协同，覆盖"什么时候写、按什么结构存、怎么检索"三个问题：

```
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 1 — 流水摘要 (memory.py)                                      │
│    何时提取：双重阈值 (token delta ≥ 500) AND (tool calls ≥ 3)        │
│             AND last turn has no pending tool_calls (safe window)   │
│    并发控制：asyncio.Lock + 60s stale force-release                  │
│    触发时机：PostSamplingHook（每次 LLM 响应后评估，嵌主循环）         │
│    产物：SESSION_MEMORY.md（时间线，[YYYY-MM-DD HH:MM] 格式追加）    │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 2 — 线段树索引 (memory_segtree.py)                             │
│    数据结构：自建 SegNode (L/R, summary, topics set, dirty, dates)   │
│    懒标记：dirty → 摘要下推合并（模板为主，LLM 版可选）              │
│    剪枝：内部节点存 topics 并集（tag 查询子树跳过）                  │
│          earliest_date/latest_date（区间查询双剪枝）                 │
│    插入：追加走根→叶路径 O(log n)，树满才翻倍重建（摊还 O(1)）      │
│    查询：query_by_tag / query_by_daterange / fuzzy_search            │
│    不变量：verify() 跑 root cover / 子树卡数 / topics 并集一致性     │
│    持久化：.mai/memory/segments.json（JSON dump 整棵子树）           │
├─────────────────────────────────────────────────────────────────────┤
│  Layer 3 — 标签卡片 + WikiLink (memory_tags.py)                       │
│    存储：每条记忆一个 .md 文件 + YAML frontmatter                    │
│           (name / description / type ∈ {user,feedback,project,ref})│
│    关联：正文用 [[name]] wiki-link 建立概念图（双向图结构）          │
│    索引：MEMORY.md 一行一条 - [Title](file.md) — hook（人读友好）   │
│    反向：tags.json 维护 tag → [name,...] 反向索引                   │
│    解析：_WIKILINK_RE 解析所有 [[...]] 提取关联图                    │
└─────────────────────────────────────────────────────────────────────┘
```

设计意图：流水层管"时序"，线段树层管"高效区间+标签检索"，卡片层管"用户可读+可编辑"。**三层互不污染**——流水的脏数据不会污染卡片；卡片层与线段树层通过写路径（save_memory/delete_memory）同步维护。

### 知识引擎

BM25 + Chroma 向量混合检索 → LLM 概念边界检测。三层：
```
文本 → ① BM25 + 向量 (粗筛 top-10)
     → ② LLM 判断是否同一概念 (精判)
     → ③ 最终结论: known / unknown → 加入学习队列
```

### 学习队列

Agent 遇到未知概念时自动加入队列。支持手动添加、标记已学、添加笔记、同步到飞书。优先级：high / medium / low。

### 桌面端

Electron 33 桌面应用，集成所有功能。支持暗色/亮色/系统主题、全局快捷键、会话管理面板、右键菜单、文件浏览选择器。

---

## 技术栈

| 层 | 选型 | 说明 |
|---|------|------|
| LLM | DeepSeek v4-pro | 主力推理模型，OpenAI 兼容 API |
| 后端 | Python 3.10+ FastAPI + asyncio | 异步非阻塞，WebSocket 原生支持 |
| 桌面 | Electron 33 + React 18 | 跨平台桌面壳，SPA 渲染 |
| 构建 | electron-vite + Vite 5 | 快速 HMR，ESBuild 转译 |
| 状态 | Zustand 4.5 | 轻量状态管理，无 Provider 包裹 |
| 样式 | Tailwind CSS 3.4 + @tailwindcss/typography | 实用优先，Markdown 排版 |
| 图标 | Lucide React 0.400 | 一致性图标系统，tree-shakable |
| Markdown | markdown-to-jsx + highlight.js | 渲染 + 13 语言语法高亮 |
| CLI | Click 8 + Rich 13 | 命令行界面 + 实时流式渲染 |
| LLM SDK | openai (OpenAI SDK) | 流式调用 DeepSeek API |
| 向量库 | ChromaDB (嵌入式) | 零配置，pip install 即用 |
| 检索 | BM25 + Chroma 向量 | 混合检索，LLM 最终裁判 |
| 飞书 | httpx (异步 HTTP) | tenant_token 认证 |
| 测试 | pytest + pytest-asyncio | 异步测试支持 |
| 打包 | electron-builder | Windows portable 输出 |

---

## 关键设计决策

### 为什么不用 LangGraph

| | LangGraph | MAI-agent 自研 |
|---|---|---|
| 状态管理 | StateGraph + checkpoint | 单例 AgentEngine + mutableMessages |
| 工具系统 | `@tool` 装饰器 + BaseTool | 自研 ToolRegistry + Pydantic Schema + Feature Flag |
| Agent 通信 | State channels | SendMessage 工具（精确控制） |
| 依赖 | 重 (langgraph + langchain + checkpoint 后端) | 轻 (openai + pydantic + fastapi + rich) |
| 可解释性 | "我用了 LangGraph" | "我分析了 Claude Code 源码，逐行复刻了工具编排和 Hook 链" |

### 为什么不是多模型路由

Claude Code 没有意图路由。把 49 个工具全给一个模型，靠 system prompt 告诉它怎么选。多模型路由的代价：
- 每请求多一次分类调用（延迟 + 费用）
- 不同 system prompt → KV Cache 全废
- 分类错误 → 工具缺失 → 无法完成任务

### 为什么用 Chroma 而不是 Milvus

个人知识库几千条概念，Chroma 嵌入式模式（`pip install`，无需 Docker）上限 100 万条。Milvus 需要 Docker + etcd + MinIO，是为百亿级向量设计的分布式系统。选型原则：刚好够的最简单的。

### 为什么用 BM25 + 向量混合检索，而不是纯向量

纯向量检索对精确术语匹配（"分布式锁" vs "分布式互斥锁"）可能漏检。BM25 做关键词补偿，LLM 做最终裁判。

### 为什么用 Zustand 而不是 Redux

- 零 Provider 包裹，不污染组件树
- `create()` 一行创建 store，`useStore(s => s.field)` 精确选择器
- 支持 `.getState()` / `.setState()` 在 React 外部读写（WebSocket 事件分发中必需）
- 体积 ~1KB vs Redux + Toolkit ~30KB

### 为什么用 WebSocket 而不是 SSE

- 双向通信：客户端需发送 `submit` / `stop` / `undo` 命令
- 工具调用流：需要 per-tool 的 start/result 事件，不是简单文本流
- 状态同步：连接建立时发送完整状态快照 (`ready` 事件)

### 为什么自研工具编排而不是用 Function Calling 默认行为

Claude Code 的并发/串行分区：
- **并发** (semaphore=10): Read, Grep, Glob, WebSearch — 只读、无副作用
- **串行**: Edit, Write, Bash, Agent — 有副作用、需顺序执行
- 标准 Function Calling 将所有 tool_call 并发执行，可能导致文件编辑冲突

### 为什么用 electron-vite 而不是 CRA / Next.js

- CRA 已停止维护，Webpack 慢
- Next.js 是 SSR 框架，桌面端只需 CSR
- electron-vite 内置主进程/渲染进程/preload 三构建通道，HMR 快

---

## 与 Claude Code 的对比

| 维度 | Claude Code | MAI-agent |
|------|-------------|-----------|
| **语言/运行时** | TypeScript + Bun | Python 3.10+ + FastAPI |
| **UI** | Ink (React TUI) + Web | Electron 33 + React 18 桌面端 |
| **工具数量** | 50+ | 49 |
| **工具编排** | 并发/串行分区 | 同，semaphore=10 |
| **权限** | auto/default/plan + 内联提示 | auto/manual/plan + y/n/a |
| **流式输出** | 原生流式 + React 渲染 | chat_stream + WebSocket events + React |
| **Bash 实时** | stdout/stderr 逐行流 | 同 |
| **Diff 显示** | 代码 diff 高亮 | +/- 逐行对比 |
| **文件快照** | 编辑前自动备份 | .mai/snapshots/ |
| **会话记忆** | 双重阈值 + postSamplingHook | 同 + asyncio.Lock + stale 保护 + 分段树索引 + 标签 |
| **Agent 孵化** | AgentTool + forked subagent | 同 + 按需孵化的四脑子 Agent |
| **MCP** | 完整支持 | 支持 (MCPToolWrapper) |
| **定时任务** | CronCreate/Delete/List | 同 |
| **任务管理** | TaskCreate/Update/Get/List/Output/Stop | 同 |
| **知识引擎** | 无 | BM25 + Chroma + LLM 边界检测 |
| **飞书集成** | 无 | 搜索/读取/写入/列表 + 学习队列同步 |
| **Worktree** | 完整 Git worktree 隔离 | 支持 (EnterWorktree/ExitWorktree/ListWorktrees) |
| **Skill 系统** | Slash Commands + .md 定义 | 同 |
| **沙箱** | Bash sandbox | 三层模式 + 路径预检 |
| **学习队列** | 无 | 自动捕获未知概念 → 标记已学 → 同步飞书 |
| **部署工具** | 无 | DeployCheck/List/Plan/Run/Rollback |
| **前端架构** | Ink (TUI) | Zustand ×10 + REST/WS 分离 |
| **测试** | Jest | pytest + pytest-asyncio, 135 tests |

---

## 开发指南

### 目录结构

```
MAI-agent/
├── mai_agent/                # 后端 Python 包
│   ├── cli.py                # CLI 入口
│   ├── config.py             # 配置管理
│   ├── context.py            # System prompt
│   ├── server.py             # FastAPI + WebSocket (27 REST 端点 + 1 WS)
│   ├── session.py            # 会话持久化
│   ├── core/
│   │   ├── engine.py         # AgentEngine
│   │   ├── loop.py           # agent_loop
│   │   └── models.py         # 数据模型
│   ├── tools/                # 49 个工具 (24 files, ~3,000 lines)
│   │   ├── base.py           # Tool 抽象基类
│   │   ├── registry.py       # 工具注册表
│   │   └── orchestration.py  # 并发/串行编排
│   ├── hooks/                # PreToolUse 门控系统
│   ├── brains/               # 四脑子 Agent 定义
│   ├── knowledge/            # 知识引擎 + 学习队列
│   ├── services/             # 记忆、飞书、MCP 客户端
│   ├── llm/                  # LLM 客户端
│   ├── skills/               # Skill 加载器
│   ├── sandbox/              # 沙箱安全策略
│   └── plugins/              # 插件系统
├── desktop/                  # Electron + React 桌面端
│   ├── package.json          # Electron 33, React 18, Zustand 4.5
│   ├── electron.vite.config.ts
│   ├── src/
│   │   ├── main/             # Electron 主进程
│   │   ├── preload/          # preload 脚本
│   │   └── renderer/         # React SPA
│   │       ├── App.tsx        # 根组件
│   │       ├── main.tsx       # React 入口
│   │       ├── components/
│   │       │   ├── chat/      # 聊天组件 (9 files)
│   │       │   ├── input/     # 输入组件 (8 files)
│   │       │   ├── common/    # 通用组件 (5 files)
│   │       │   ├── panels/    # 侧面板 (5 files)
│   │       │   ├── sidebar/   # 侧栏 (5 files)
│   │       │   ├── settings/  # 设置 (1 file)
│   │       │   └── status/    # 状态栏 (2 files)
│   │       ├── stores/        # Zustand stores (10 files)
│   │       ├── hooks/         # 自定义 hooks (6 files)
│   │       ├── lib/           # 工具库 (4 files)
│   │       └── types/         # TypeScript 类型 (9 files)
│   └── assets/               # 图标、字体等静态资源
├── tests/                    # 测试 (135 tests)
├── pyproject.toml
└── README.md
```

### 开发模式启动

```bash
# 终端 1: 启动后端
python -m mai_agent.cli --serve --port 8765

# 终端 2: 启动前端
cd desktop && npm run dev
# → Electron 窗口打开，Vite HMR 热更新
```

### 构建生产版本

```bash
# 构建桌面端
cd desktop && npm run build

# 打包 Windows 便携版
cd desktop && npm run package
# → desktop/dist/MAI-agent.exe
```

### 运行测试

```bash
pytest tests/ -v          # 135 tests
pytest tests/ --cov        # 覆盖率 (需 pytest-cov)
pytest tests/ -k "memory"  # 按名称过滤
```

### 添加新工具

1. 在 `mai_agent/tools/` 创建 `my_tool.py`
2. 继承 `Tool` 基类，实现 `name`, `description`, `input_schema`, `run()`
3. 在文件末尾调用 `registry.register(MyTool())`
4. 工具自动出现在 `/api/tools` 和 WebSocket `ready` 事件中
5. 前端 `useToolStore` 自动拉取并展示

### 添加新面板

1. 在 `desktop/src/renderer/components/panels/` 创建 `MyPanel.tsx`
2. 如需要新 store: 在 `stores/` 创建 `myStore.ts` (使用 `zustand create`)
3. 添加 API 端点到 `lib/api.ts`
4. 在 `PanelContainer.tsx` 和 `SidebarIconBar.tsx` 注册面板入口
5. 在 `stores/uiStore.ts` 更新 `PanelType` 类型

---

## License

MIT
