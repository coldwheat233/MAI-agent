---
name: mai-hooks
description: Hook 体系 Skill。PreToolUse 权限门控、PostToolUse 审计、HookRegistry/disposer、permission_mode（auto/manual/plan）语义。
whenToUse: 改权限模式 / 加审计·通知·拦截 hook / Hook 注册与卸载 / 危险命令门控
---

# mai-hooks

三道防线中的 Hook 层。所有工具执行前/后都会过这里。

## 关键位置

- `mai_agent/hooks/types.py` — `HookEvent`（PRE_TOOL_USE / POST_TOOL_USE）、`HookRegistry`（disposer 模式注册/卸载）
- `mai_agent/hooks/executor.py` — `execute_hooks(event, tool_name, tool_input, reg)` 跑 hook 链
- `mai_agent/hooks/gate.py` — `can_use_tool()` 三层判定：
  1. hook 链：`deny` → 拦；`ask` → manual 弹用户、auto/plan 自动拒
  2. plan 模式只读工具白名单
  3. auto/manual 通过即放行
- `mai_agent/hooks/builtins.py` — 内置策略（guardrails 危险命令拦截等）

## 用法

- hook 返回 decision（deny/ask/allow），可带 `modified_input` 改写工具参数
- 注册返回 disposer，可卸载；hook 失败只 debug 记日志，**不能中断工具执行**

## 红线

- **顺序约束**：PostToolUse hook 在 trace span 记录之后、`tool_result` progress 之前调用（审计 payload 依赖 `tool_result/duration_ms`）——见 `mai-core-loop` invariants
- deny 必须带 `reason`：LLM 会看到 `[DENIED] reason` 并据此调整策略
- 权限模式切换走 `engine.set_mode()`（同时改 RunContext + LoopConfig），别只改一处

## 边界

- 改工具本身逻辑 → `mai-tools`
- 改 LLM 重试/fallback → `mai-llm`
