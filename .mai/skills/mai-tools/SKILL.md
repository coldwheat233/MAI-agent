---
name: mai-tools
description: 工具体系 Skill。新增工具、改工具执行逻辑、工具 schema、并发/串行编排（只读并发/独立写并发/共享写串行）时使用。
whenToUse: 新增或修改 MAI-agent 工具（文件/Git/Shell/Web/记忆/定时/部署等 50+ 工具）
---

# mai-tools

工具注册、基类管道与编排层。**改工具前先看位置与红线。**

## 关键位置

- `mai_agent/tools/base.py` — `Tool` 基类：
  - `execute()` 管道：注入 `_tool_use_id` → Pydantic 校验 → `call()` → 包装 `ToolResult`
  - `is_concurrency_safe`（True=只读，可与其他只读并发）
  - `write_targets()`（写工具声明写目标，参与"独立写并发"判定）
- `mai_agent/tools/registry.py` — 注册表 + `to_openai_schemas(permission_mode)` 白名单/权限过滤 + schema 压缩
- `mai_agent/tools/orchestration.py` — `run_tools()`：分区执行（只读并发 → 独立写并发 → 共享写/副作用串行，`Semaphore(10)`）；`partition_by_safety()` 返回**三元组** `(reads, concurrent_writes, serial)`
- `mai_agent/tools/__init__.py` — 模块注册面（import 即注册）
- 各工具文件：`file_*.py / git_tools.py / bash.py / web_*.py / memory_tools.py / cron_tools.py / workflow_tool.py / agent_tool.py / deploy_tools.py / feishu_tools.py / task_tools.py / ...`

## 新增工具三步

1. 定义 `XxxInput(ToolInput)`（`extra="forbid"`）+ `XxxTool(Tool)`，实现 `async call()`
2. 文件底部 `registry.register(XxxTool())`
3. 在 `tools/__init__.py` 顶部 import 该模块

## 红线

- `execute()` 会往参数注入 `_tool_use_id`——call 里别覆盖、别丢
- **失败返回 `"[ERROR] ..."` 字符串**（loop 据此判 `is_error`），不要抛异常炸调用链
- 只读设 `is_concurrency_safe=True`；写工具覆盖 `write_targets()` 声明目标；目标无法静态判定（如 Bash）返回 `[]` → 自动降串行（安全优先）
- 不要在自己工具里调 `can_use_tool`/权限门控——gate 已在 agent_loop 前置统一处理
- 描述会被 schema 压缩截断（description≤120 字符、参数 description≤60），别依赖超长描述
- 改工具**失败不回滚**是语义（LLM 看到错误重新决策），别引入 Saga 补偿

## 边界

- 改 agent 循环/消息流转/上下文 → `mai-core-loop`
- 改权限门控/Hook → `mai-hooks`
