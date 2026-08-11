"""Tests for knowledge engine: BM25 search, KnowledgeStore."""

import asyncio
import shutil

import pytest

from mai_agent.knowledge.vector_store import _BM25Index, KnowledgeStore


class TestBM25:
    def test_empty(self):
        bm25 = _BM25Index()
        assert bm25.search("anything") == []

    def test_exact_match(self):
        bm25 = _BM25Index()
        bm25.add("a", "分布式锁 协调多进程对共享资源的互斥访问")
        results = bm25.search("分布式锁")
        assert len(results) == 1
        assert results[0][0] == "a"

    def test_partial_match_chinese(self):
        bm25 = _BM25Index()
        bm25.add("a", "分布式锁: 互斥访问共享资源")
        bm25.add("b", "KV Cache: LLM推理缓存机制")
        # "分布式互斥" should match doc a via bigram "互斥"
        results = bm25.search("分布式互斥")
        assert len(results) >= 1
        assert results[0][0] == "a"

    def test_no_match(self):
        bm25 = _BM25Index()
        bm25.add("a", "分布式锁")
        results = bm25.search("React Hooks")
        assert len(results) == 0

    def test_multiple_docs_ranked(self):
        bm25 = _BM25Index()
        bm25.add("a", "分布式锁 Redis实现")
        bm25.add("b", "分布式文件系统 存储")
        bm25.add("c", "分布式锁 ZooKeeper实现 互斥")
        results = bm25.search("分布式锁 互斥 Redis")
        assert len(results) >= 2
        # doc c has "分布式锁" + "互斥", doc a has "分布式锁" + "Redis"
        # Both should score
        assert results[0][0] in ("a", "c")

    def test_remove(self):
        bm25 = _BM25Index()
        bm25.add("a", "test content")
        bm25.remove("a")
        assert bm25.search("test") == []


class TestKnowledgeStore:
    @pytest.mark.asyncio
    async def test_add_and_search_bm25(self):
        store = KnowledgeStore(".mai/test_ks")
        try:
            await store.add("k1", "FastAPI Python web framework for building APIs")
            await store.add("k2", "Django Python web framework with ORM")
            await store.add("k3", "SpringBoot Java web framework")

            count = await store.count()
            assert count == 3

            results = await store.search("Python API", alpha=0.0)  # BM25 only
            assert len(results) >= 1
            assert results[0]["id"] in ("k1", "k2")  # Both match, order depends on BM25 scoring
        finally:
            shutil.rmtree(".mai/test_ks", ignore_errors=True)

    @pytest.mark.asyncio
    async def test_delete(self):
        store = KnowledgeStore(".mai/test_ks2")
        try:
            await store.add("x", "to be deleted")
            assert await store.count() == 1
            await store.delete("x")
            assert await store.count() == 0
        finally:
            shutil.rmtree(".mai/test_ks2", ignore_errors=True)

    @pytest.mark.asyncio
    async def test_no_match(self):
        store = KnowledgeStore(".mai/test_ks3")
        try:
            await store.add("x", "Python async programming")
            results = await store.search("Rust borrow checker", alpha=0.0)
            assert len(results) == 0
        finally:
            shutil.rmtree(".mai/test_ks3", ignore_errors=True)
