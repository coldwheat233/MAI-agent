---
name: mai-repo-map
description: MAI-agent 仓库导航 Skill。用于快速判断需求应该落到哪个 Python 模块、哪个工具、哪一层（core/tools/hooks/services/knowledge）。当需求入口不清晰、需要先找模块边界、模块依赖或改动影响面时使用。
whenToUse: 新需求不知道改哪里 / 需要先了解模块职责 / 需要找关键入口 / 需要确认改动影响面
---

# mai-repo-map

先用这层做路由，再切到对应模块 Skill。

## 使用顺序

1. 先看 `references/generated-module-map.md`（脚本自动生成，71 个模块摘要 + 依赖），把需求归到一个主模块。
2. 再看下面的「路由原则」，切到对应领域 Skill。
3. 如果需求涉及改 agent 循环、改工具、改 Hook 或跨多个模块，立刻切到对应 Skill，不要长期停留在路由层。

## 路由原则

- 需求涉及 agent 主循环、消息流转、上下文管理、LLM 调用 → `mai-core-loop`
- 需求涉及工具注册、工具编排（并发/串行）、工具 schema → `mai-tools`
- 需求涉及权限门控、审计、Hook 注册 → `mai-hooks`
- 需求涉及多模型切换、Provider、重试/fallback → `mai-llm`
- 需求涉及记忆（卡片/线段树/会话摘要）、Trace → `mai-services`
- 需求涉及知识检索（BM25/向量）、概念检测 → `mai-knowledge`
- 需求涉及 MCP 服务器、.mcp.json → `mai-mcp`
- 需求同时改多个模块、涉及不可破坏约束 → 先看本文档「修改注意事项」再动手

## 什么时候继续下钻

- 需求已明确落到某个模块/函数时，不要继续停在 repo-map。
- 需要确认某模块的不可破坏约束（invariants）时，优先打开对应 Skill 的 references。
- 如果已知道要改哪一层，直接切换 Skill，不要二次路由。

## 参考资料

- `references/generated-module-map.md`（脚本生成，勿手改 — 运行 `python skills/scripts/extract_module_map.py` 重新生成）
- `scripts/extract_module_map.py`
