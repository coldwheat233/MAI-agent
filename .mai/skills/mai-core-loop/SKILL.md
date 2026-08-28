---
name: mai-core-loop
description: Agent 核心循环与引擎 Skill。改 agent_loop、消息流转、上下文压缩、引擎生命周期（start/submit/stop）、热切换时使用。
whenToUse: 修改 agent 主循环 / 消息处理 / 上下文管理 / LLM 调用 / 引擎状态机 / 会话生命周期
---

# mai-core-loop

Agent 最核心的模块：思考-行动-观察循环 + 引擎生命周期。**改这里前必读 invariants。**

## 使用顺序

1. 先读 `references/invariants.md`（红线清单，改了会炸的 9 条）。
2. 再看 `mai-repo-map` 的 `generated-module-map.md` 定位具体函数。
3. 涉及工具编排/权限/Hook 时切到对应 Skill（`mai-tools` / `mai-hooks`）。

## 关键入口

- `agent_loop()`（loop.py）— 主循环：LLM 调用 → 工具执行 → 结果回传
- `AgentEngine.start()/submit()/stop()`（engine.py）— 会话生命周期
- `AgentEngine.switch_model()` — 热切换（不重建引擎）
- `AgentEngine.start_trace()` — trace recorder 启动（异步上下文）
- `strip_incomplete_tool_calls()` — 消息清洗（删消息必须走这里）

## 必守约束（速查）

- assistant(tool_calls) 必须紧跟等量 tool 回复（`strip_incomplete_tool_calls`）
- 上下文压缩切分点必须在 user 边界
- start() 里不要调 asyncio.get_running_loop()
- submit 前先 commit UserMessage
- 热切换不重建引擎

## 不要用我做什么

- 不要用本 Skill 改工具本身的逻辑（那属于 `mai-tools`）
- 不要用本 Skill 改 Hook 注册/门控（那属于 `mai-hooks`）
- 不要用本 Skill 改 LLM 客户端重试/fallback（那属于 `mai-llm`）
