# mai-core-loop — Invariants（不可破坏约束）

改 `mai_agent/core/loop.py` / `core/engine.py` 前必须检查的红线清单。

## 消息协议约束（违反会 API 400）

1. **assistant(tool_calls) 后必须紧跟等量 tool 回复**
   - OpenAI/DeepSeek 要求每条 tool_call 有对应 role=tool 消息，缺一条就 400。
   - 删除消息时必须走 `strip_incomplete_tool_calls()`（loop.py 底部），**禁止手工截断中间段**——会把 tool_calls 与 tool 回复拆散。
2. **上下文压缩的切分点必须落在 user 消息边界**
   - `_compact_context` 的 split 点不能落在 assistant(tool_calls) 上，否则产生孤儿 tool 消息。代码里用 while 循环回退到 user/system 边界——别改成简单下标切分。

## 引擎生命周期约束

3. **`engine.start()` 可能在 to_thread 线程池里执行**（server 的 init_engine 路径）——**不要**在 start() 里调用 `asyncio.get_running_loop()`（会抛 RuntimeError 被吞掉）。trace recorder 只挂载不启动，由异步上下文 `start_trace()` 启动。
4. **`_session_id` 必须在 `__init__` 里、RunContext 创建之前赋值**——RunContext.session_id 依赖它。曾因顺序错误导致 AttributeError（2026-08-19 修过）。
5. **热切换模型不重建引擎**：`switch_model()` 只 reconfigure LLMClient，session/messages 保留。不要在热切换里 pop 引擎重建（那是旧的 /api/model 行为，已废弃）。

## 提交/取消约束

6. **submit 前必须先把 UserMessage commit 进 self._messages**——否则流中被 cancel 时该条 user 消息丢失，重发会"抹掉最近一条回复"（用户明确禁止）。
7. **CancelledError 兜底**：agent_loop 被取消时，已流出的部分内容要落进 messages，且必须清理不完整的 tool_calls（`strip_incomplete_tool_calls`）——否则下次加载会话再提交会 400。

## 工具执行约束

8. **工具失败不回滚**（独立写并发语义）——错误结果交回 LLM 重新决策，不要引入 Saga 补偿。
9. **PostToolUse hooks 在 trace 记录之后、progress 之前调用**——顺序别乱改，审计依赖 payload 里的 tool_result/duration_ms。
