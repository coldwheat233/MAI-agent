"""P0-1 回归：卡片向量索引在事件循环内真正生效（不再 asyncio.run 静默失败）。

旧 bug：memory_vector 用 asyncio.run() 包 async 调用，而 MemoryWrite/Search
工具运行在 agent_loop 的事件循环线程里 → RuntimeError → 静默 return False，
向量索引/语义召回在活体使用中从不生效（只在同步测试里通）。

本套件用 FakeStore 替换 chroma/embedding（全离线），断言在 running loop 中
index/delete/search 都被真正 await 到。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mai_agent.services import memory_tags, memory_vector
from mai_agent.services.memory_tags import TaggedMemory


class FakeStore:
    """记录调用的假 KnowledgeStore（不碰 chroma/模型）。"""

    def __init__(self):
        self.added: list[tuple] = []
        self.deleted: list[str] = []
        self.search_results: list[dict] = []

    async def add(self, doc_id, text, metadata=None):
        self.added.append((doc_id, text, metadata))

    async def delete(self, doc_id):
        self.deleted.append(doc_id)

    async def search(self, query, top_k=8, alpha=0.7):
        return list(self.search_results)


def _install_fake_store(monkeypatch, tmp_path: Path) -> FakeStore:
    store = FakeStore()
    monkeypatch.setattr(memory_vector, "_get_store", lambda root: store)
    return store


def _make_card(name: str = "distributed-lock") -> TaggedMemory:
    return TaggedMemory(
        name=name,
        description="分布式锁三种实现与选型",
        type="reference",
        tags=["分布式", "并发"],
        content="正文 [[redis]] 关联",
        created_at="2026-01-01",
    )


class TestIndexCardInRunningLoop:
    def test_save_memory_indexes_card(self, tmp_path, monkeypatch):
        store = _install_fake_store(monkeypatch, tmp_path)

        async def main():
            # save_memory 已是 async：这正是 MemoryWriteTool 在 agent_loop 里的调用形态
            path = await memory_tags.save_memory(_make_card(), str(tmp_path))
            return path

        path = asyncio.run(main())
        assert Path(path).exists()
        # 回归点：旧实现在 running loop 里 asyncio.run 抛 RuntimeError → added 为空
        assert len(store.added) == 1, "索引调用必须真正执行（不能因 asyncio.run 静默失败）"
        doc_id, text, meta = store.added[0]
        assert doc_id == "distributed-lock"
        assert meta == {"type": "card"}
        assert "分布式锁" in text
        # P1-3 联动：懒初始化（卡先存在→树后建）也必须落盘 segments.json
        seg = tmp_path / ".mai" / "memory" / "segments.json"
        assert seg.exists(), "懒初始化时序下段树必须落盘"

    def test_update_existing_card_reindexes_tree(self, tmp_path, monkeypatch):
        _install_fake_store(monkeypatch, tmp_path)

        async def main():
            card = _make_card()
            await memory_tags.save_memory(card, str(tmp_path))
            # 更新既有卡片（MemoryWrite 对已存在 name 是 update 语义）
            card.description = "更新后的描述"
            card.tags = ["分布式", "并发", "锁"]
            await memory_tags.save_memory(card, str(tmp_path))
            return memory_tags.get_tree(str(tmp_path))

        tree = asyncio.run(main())
        assert tree is not None and tree.root is not None
        # 更新后树里仍只有 1 张卡（不重复插入）
        assert tree.cards == ["distributed-lock"]
        assert len(tree.query_by_tag("锁")) == 1

    def test_delete_memory_removes_from_store(self, tmp_path, monkeypatch):
        store = _install_fake_store(monkeypatch, tmp_path)

        async def main():
            await memory_tags.save_memory(_make_card(), str(tmp_path))
            ok = await memory_tags.delete_memory("distributed-lock", str(tmp_path))
            return ok

        assert asyncio.run(main()) is True
        assert store.deleted == ["distributed-lock"]
        assert not (tmp_path / ".mai" / "memory" / "distributed-lock.md").exists()

    def test_semantic_search_in_running_loop(self, tmp_path, monkeypatch):
        store = _install_fake_store(monkeypatch, tmp_path)
        # 先建一张真实卡片文件，FakeStore 的 search 返回它
        async def setup():
            await memory_tags.save_memory(_make_card(), str(tmp_path))

        asyncio.run(setup())
        store.search_results = [{"id": "distributed-lock", "score": 0.91}]

        async def main():
            results = await memory_vector.semantic_search("和缓存类似的东西", str(tmp_path))
            return results

        results = asyncio.run(main())
        assert len(results) == 1
        assert results[0].name == "distributed-lock"
        assert abs(results[0]._semantic_score - 0.91) < 1e-6

    def test_search_hybrid_path_awaits_semantic(self, tmp_path, monkeypatch):
        store = _install_fake_store(monkeypatch, tmp_path)

        async def main():
            await memory_tags.save_memory(_make_card(), str(tmp_path))
            # 关键词 miss（无 tag/内容命中）→ 语义补召回
            store.search_results = [{"id": "distributed-lock", "score": 0.8}]
            hits = await memory_tags.search("完全无关的关键词zzz", str(tmp_path))
            return hits

        hits = asyncio.run(main())
        assert [m.name for m in hits] == ["distributed-lock"]

    def test_reindex_all(self, tmp_path, monkeypatch):
        store = _install_fake_store(monkeypatch, tmp_path)

        async def main():
            await memory_tags.save_memory(_make_card("card-a"), str(tmp_path))
            await memory_tags.save_memory(_make_card("card-b"), str(tmp_path))
            store.added.clear()
            return await memory_vector.reindex_all(str(tmp_path))

        assert asyncio.run(main()) == 2
        assert {a[0] for a in store.added} == {"card-a", "card-b"}
