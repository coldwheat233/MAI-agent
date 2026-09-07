---
name: mai-knowledge
description: 知识引擎 Skill。概念提取/边界检测、chroma+BM25 混合检索、本地/API embedding、学习队列。
whenToUse: 改知识检索（BM25/向量）、概念检测、embedding 后端、learning queue
---

# mai-knowledge

"未知概念发现 + 知识检索"子系统（与记忆卡片是两层，别混）。

## 关键位置

- `knowledge/vector_store.py` — `KnowledgeStore`：chroma 向量 + 自研 BM25 双索引合并排序；`_NoOpEmbeddingFunction`（外部 embedding 显式传入）；`get_store(persist_dir)` **按目录缓存实例**
- `knowledge/embedding.py` — `LocalTransformer`（本地 bge 系列，async 懒加载）/ `APIEmbedding`；`create_embedding`
- `knowledge/concept_detector.py` — LLM 抽概念 → 查库边界检测 → 标复杂度
- `knowledge/learning_queue.py` — 待学队列（含飞书同步字段）
- 入口：`engine._detect_concepts()` 每次 submit 后台跑（extract → check_boundary → 入库/入队），失败只 debug

## 红线

- **store 实例按 persist_dir 缓存别丢**——BM25 索引跨调用累积，每次 new 会让边界检测退化"永远未知"
- chroma 落 `.mai/chroma`，与卡片向量（`memory_vector`）共用目录——文档语义靠 `metadata.type` 区分（"concept" vs "card"），别混用 doc_id
- embedding 不可用 → 自动降级 BM25-only 是**特性**（代码注释明确），别改成抛异常
- LocalTransformer 是 CPU 模型，首次加载慢；encode 走 async 接口
- 记忆卡片读写 → `mai-services`，别绕到本层

## 边界

- 会话摘要/标签卡片/段树/向量索引 → `mai-services`
