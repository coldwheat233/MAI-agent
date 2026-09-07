---
name: mai-services
description: 记忆与观测服务 Skill。会话流水摘要（双阈值）、标签卡片、H2Mem 线段树、卡片向量索引、Trace/结构化日志、飞书、MCP client。
whenToUse: 改记忆链路（卡片/段树/摘要/向量）、Trace/日志、飞书服务
---

# mai-services

持久化与观测服务层。**记忆链路改前必读红线（异步 + 落盘）。**

## 关键位置

- `services/memory.py` — SESSION_MEMORY.md 自动流水摘要；`should_extract` 双阈值（token 增量≥500 **且** tool 调用≥3 + 安全窗口=末轮无 pending tool_calls）
- `services/memory_tags.py` — 标签卡片（.md+YAML frontmatter）、`MEMORY.md`/`tags.json` 索引、`save_memory/delete_memory/search`（关键词+语义混合）
- `services/memory_segtree.py` — H2Mem 段树：时间有序卡片数组 + 内部节点 topics 并集/日期范围/摘要（dirty 懒重算）；`save()/load()` 落盘 `.mai/memory/segments.json`
- `services/memory_vector.py` — 卡片向量语义召回（复用 knowledge 的 chroma+BM25）
- `services/trace.py` / `structured_logger.py` — span 轨迹与 JSONL 日志（`.mai/traces|logs`）
- `services/feishu.py` / `mcp_client.py` — 飞书 API、MCP stdio client

## 红线

- **记忆写入/检索是 async 链路：必须在 async 函数里 `await`，禁止 `asyncio.run`**——在 agent_loop 事件循环线程里会 RuntimeError 静默失效（回归见 `tests/test_memory_vector_async.py`）
- 写卡片顺序：写 .md → `rebuild_index` → segtree insert **+ `tree.save()`** → 向量 upsert；删卡对称
- segtree 不变量：叶子 card_count 0/1、内部节点 topics = 左右并集、边界连续（`tree.verify()` 自查）；卡片文件是源，segments.json 是缓存
- 卡片更新/懒初始化场景：同名先 `remove` 再 `insert`（见 `memory_tags._maybe_insert_tree`），否则"卡片已存在"
- Trace/日志写入失败只 debug，不阻断主流程

## 边界

- 概念检测/知识库/学习队列 → `mai-knowledge`
