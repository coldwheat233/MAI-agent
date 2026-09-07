---
name: mai-llm
description: LLM 客户端与 Provider Skill。调用协议、流式解析、重试/容灾、Provider 注册表、模型热切换。
whenToUse: 改 LLM 调用/流式/重试/fallback、增删 Provider、模型热切换、usage 统计
---

# mai-llm

LLM 层：OpenAI 兼容协议 + DeepSeek 为主 + Provider 容灾。

## 关键位置

- `mai_agent/llm/client.py` — `LLMClient`：
  - `chat()` / `chat_stream()`（流式 text_delta / tc_delta / usage）
  - `_retry_loop()` 重试
  - `set_fallback_providers()` 主 provider 失败自动切备用
  - `reconfigure()` 热切换（不重建）
- `mai_agent/llm/providers.py` — `list_providers()` / `resolve_provider()` / 协议与 .env 持久化
- `mai_agent/core/loop.py` — `messages_to_openai()`（内部消息→OpenAI 格式，单点转换）

## 红线

- **热切换只 reconfigure base_url/api_key/model**——不重建引擎、不丢 messages（对齐 `engine.switch_model()`）
- DeepSeek 流式响应通常**不带 usage**（include_usage 不生效）→ Trace 用 4 char≈1 token 估算并标 `usage_estimated`；API 返回真实 usage 才优先用
- 流式中途异常由 agent_loop 的 try/except 兜底：已有文本且无 tool_calls 当收敛（拼 `(stream interrupted)`），完全无内容才 re-raise
- 消息历史格式/工具 schema 的组装在 loop 层，别绕过 `messages_to_openai`
- fallback 只在"有 key 的备用 provider"里选（engine 构造时算好）

## 边界

- 改工具 → `mai-tools`；改引擎生命周期 → `mai-core-loop`
