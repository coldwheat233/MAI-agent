# MAI-agent

以 Claude Code 架构为地基的**单进程个人 AI 开发 Agent**：Python 后端内核（~15K 行，FastAPI + WebSocket）+ Electron/React 桌面端。不依赖 LangChain 等重框架，工具循环、上下文管理、记忆、Hook、沙箱、Trace 全部手写轻量自研。

## 核心能力

- **AgentLoop 工具循环** — OpenAI 兼容流式协议，23 个内置工具（文件/Shell/Git/Web/子 Agent/部署/记忆/定时任务），三区并发编排（只读并发 / 独立写并发 / 共享写串行）
- **双层上下文管理** — 出发前预算式 system prompt 组装（P1/P2/P3 优先级 + full→summary→omit 三档降级），途中 80% 阈值 LLM 摘要压缩；对话中任意时刻中断不丢历史
- **三层记忆 + 知识边界** — 会话记忆自动提取、时间序线段树摘要（O(log n) 区间检索 + 懒标记延迟摘要）、标签卡片（wiki-link 互联 + 向量语义检索）；基于本人笔记语料的概念边界检测，未知概念自动进学习队列
- **纵深安全** — Hook 门控（allow/deny/ask + 参数改写）→ plan 模式只读白名单 → per-engine 沙箱三级策略（命令静态审查 + 写路径越界判定双通道）
- **LLM 容灾** — 指数退避重试 + provider 级 fallback（保持客户端对象身份，热切换模型不丢上下文）
- **扩展机制** — MCP 懒加载代理（N 份工具 schema → 1 个代理工具，上下文成本 6K→300 tokens）、Skill 按需激活、插件动态加载、进程内 Cron 调度
- **桌面端** — Electron + React + Zustand，REST（管理面）+ WebSocket（流式交互面）双通道，多工作区引擎池，Trace 语义化展示（label/category 徽标 + 成本统计）

## 快速开始

```bash
# 安装（Python 3.12+）
pip install -e .
pip install -e ".[knowledge]"   # 可选：向量知识库（chromadb + sentence-transformers）
pip install -e ".[dev]"         # 可选：测试

# 配置
cp .env.example .env            # 填入 LLM_API_KEY（默认 DeepSeek，OpenAI 兼容端点均可）

# 运行
mai --desktop        # 启动桌面应用（推荐，后端自动拉起）
mai                  # 终端 REPL
mai --once "任务"    # 单次执行
```

## 启动架构

`mai --desktop` 是唯一完整入口：CLI 仅作为引导员 spawn Electron 并传入 `MAI_PORT` / `MAI_PYTHON` / `MAI_PROJECT_ROOT`；**Electron 主进程是后端唯一启动者**（开发模式 spawn 系统 Python 跑 uvicorn，打包模式 spawn PyInstaller 自包含 backend.exe），工作目录钉死在项目根，保证 `.mai/` 运行时数据与会话库（`~/.mai/mai.db`）位置唯一。

```
┌─────────────────────────────────────────────────────┐
│ Electron 壳 (desktop/)  React18 + Zustand + TS      │
│      REST /api/*  ·  WebSocket /ws 流式事件          │
├─────────────────────────────────────────────────────┤
│ FastAPI (server.py)  :8765  多工作区引擎池            │
├─────────────────────────────────────────────────────┤
│ AgentEngine → AgentLoop（消息循环·压缩·崩溃安全）      │
│      ↓        ↓         ↓           ↓               │
│  上下文组装   三层记忆   知识边界     LLM 客户端       │
├─────────────────────────────────────────────────────┤
│ 工具系统 (tools/)  注册表 + 三区并发编排               │
├─────────────────────────────────────────────────────┤
│ 安全层  Hook 门控 → plan 白名单 → 沙箱 (per-engine)   │
└─────────────────────────────────────────────────────┘
```

## 目录结构

```
MAI-agent/
├── mai_agent/            核心源码
│   ├── cli.py            CLI 入口（desktop/REPL/once 三模式）
│   ├── server.py         FastAPI + WebSocket 后端
│   ├── db.py             SQLite 持久层（~/.mai/mai.db，会话/消息/工作区）
│   ├── context.py        上下文聚合（七层 system prompt）
│   ├── core/             AgentEngine（会话生命周期）+ agent_loop（主循环）
│   ├── tools/            23 个工具模块 + 注册表 + 并发编排
│   ├── hooks/            Hook 门控系统（Pre/PostToolUse）
│   ├── sandbox/          三级命令安全策略
│   ├── services/         记忆×3 / 概念检测 / Trace / 上下文组装 / Cron / MCP 客户端
│   ├── knowledge/        向量存储（Chroma + 手写 BM25 混合检索）/ embedding
│   ├── brains/           子 Agent 角色定义（explorer/validator/knowledge/deploy）
│   ├── skills/           Skill 加载器
│   ├── plugins/          插件动态加载
│   └── llm/              OpenAI 兼容客户端 + 多 provider 管理
├── desktop/              Electron/React 桌面端（主进程 / preload / 渲染进程）
├── tests/                pytest 测试套件
├── eval/                 任务集评估（eval_runner.py 回归 + 知识库灌库脚本）
├── backend_entry.py      PyInstaller 打包入口
└── .mai/                 运行时数据（记忆/trace/日志/向量库/Skill，已 gitignore）
```

## 测试与评估

```bash
pytest                              # 单元测试（50 用例：segtree 持久化 / 会话清理 / cron / 插件注册等）
python eval_runner.py               # 任务集回归评估（完成率/步数/token/成本量化报告）
python eval_runner.py --judge       # 附加 LLM-as-judge 质量打分
python eval/seed_knowledge.py       # 向个人知识库灌入笔记语料（bge-large-zh 本地 embedding）
```

## 配置

环境变量见 `.env.example`：`LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` / `MAX_STEPS`，可选 `TAVILY_API_KEY`（WebSearch 三层回退的最优先源：Tavily → Bing 直连 → DuckDuckGo）。运行时可通过桌面端或 API 热切换 provider / 模型 / 权限模式 / 沙箱模式，无需重启。
