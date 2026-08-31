"""卡片向量索引 — 让"我做过的东西"支持语义检索（向量 + 关键词混合）。

设计:
  - 卡片（.mai/memory/*.md）内容向量化进 KnowledgeStore（chroma + BM25 双索引）
  - 检索时: 关键词命中（现有 fuzzy_search）+ 向量语义召回（新增）合并去重
  - 增量维护: save_memory → 同步 upsert; delete_memory → 同步删除

与 memory_tags 的关系:
  - memory_tags.search() 负责关键词检索（回源读文件）
  - 本模块负责向量语义召回，search() 里合并两者
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from mai_agent.knowledge.vector_store import KnowledgeStore
from mai_agent.knowledge.embedding import create_embedding
from mai_agent.services.memory_tags import TaggedMemory, load_all_memories, load_memory_by_name

logger = logging.getLogger(__name__)

# 每个工作区一个 KnowledgeStore 缓存（卡片向量索引复用 chroma 持久化）
_stores: dict[str, KnowledgeStore] = {}
_embedding_cache: dict[str, object] = {}


def _get_store(project_root: str) -> Optional[KnowledgeStore]:
    """获取（或创建）工作区的卡片向量存储。

    复用 KnowledgeStore（chroma + BM25 混合检索），embedding 用本地 bge-small-zh
    （已缓存，避免 bge-m3 2.2GB 下载）。embedding 不可用时返回 None（纯关键词）。
    """
    key = str(Path(project_root).resolve())
    if key in _stores:
        return _stores[key]
    try:
        embedding = _embedding_cache.get(key)
        if embedding is None:
            from mai_agent.knowledge.embedding import LocalTransformer
            # 优先用已缓存的 bge-small-zh；否则 fallback 默认（可能触发下载，失败降级）
            cached = Path.home() / ".cache" / "huggingface" / "hub" / "models--BAAI--bge-small-zh-v1.5" / "snapshots"
            model = None
            if cached.exists():
                snaps = list(cached.iterdir())
                if snaps:
                    model = str(snaps[0])
            embedding = LocalTransformer(model_name=model) if model else create_embedding("local")
            _embedding_cache[key] = embedding
        store = KnowledgeStore(
            persist_dir=str(Path(project_root) / ".mai" / "chroma"),
            embedding_backend=embedding,
        )
        _stores[key] = store
        return store
    except Exception as exc:
        logger.warning("卡片向量索引不可用（降级纯关键词）: %s", exc)
        return None


def index_card(memory: TaggedMemory, project_root: str = ".") -> bool:
    """索引一张卡片到向量库（doc_id = 卡片名）。"""
    store = _get_store(project_root)
    if store is None:
        return False
    try:
        import asyncio
        text = "\n".join([
            memory.name,
            memory.description,
            " ".join(memory.tags),
            memory.content or "",
        ]).strip()
        if not text:
            return False
        # 同步到事件循环（调用方可能是同步上下文）
        asyncio.run(store.add(memory.name, text, metadata={"type": "card"}))
        return True
    except Exception as exc:
        logger.debug("卡片索引失败 %s: %s", memory.name, exc)
        return False


def remove_card(name: str, project_root: str = ".") -> bool:
    """从向量库删除卡片索引。"""
    store = _get_store(project_root)
    if store is None:
        return False
    try:
        import asyncio
        asyncio.run(store.delete(name))
        return True
    except Exception as exc:
        logger.debug("卡片索引删除失败 %s: %s", name, exc)
        return False


def semantic_search(query: str, project_root: str = ".", top_k: int = 8) -> list[TaggedMemory]:
    """向量语义召回卡片（与关键词互补——搜"和缓存类似的东西"能命中）。

    返回按相似度排序的卡片列表。
    """
    store = _get_store(project_root)
    if store is None:
        return []
    try:
        import asyncio
        results = asyncio.run(store.search(query, top_k=top_k, alpha=0.7))
        cards = []
        for r in results:
            mem = load_memory_by_name(r["id"], project_root)
            if mem:
                mem._semantic_score = r.get("score", 0.0)  # type: ignore[attr-defined]
                cards.append(mem)
        return cards
    except Exception as exc:
        logger.debug("卡片语义检索失败: %s", exc)
        return []


def reindex_all(project_root: str = ".") -> int:
    """全量重建卡片向量索引（新增/批量导入时调用）。"""
    count = 0
    for mem in load_all_memories(project_root):
        if index_card(mem, project_root):
            count += 1
    return count
