"""P1-3 回归：记忆线段树落盘闭环（segments.json 持久化 + 摘要 + 检索）。

旧缺口：生产代码从不调 tree.save()，segments.json 永不落盘；每次引擎启动
从卡片全量重建树、摘要丢失。现在 memory_tags 写/删卡片时同步 tree.save()，
引擎可选 MAI_SEGTREE_LLM_SUMMARY=1 跑 LLM 摘要并落盘（本套件用模板摘要）。
"""

from __future__ import annotations

import json
from datetime import date

from mai_agent.services.memory_segtree import MemorySegTree
from mai_agent.services import memory_tags


def _seed_card(root, name: str, desc: str, tags: list[str], created: str) -> None:
    d = root / ".mai" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        "type: reference\n"
        f"tags: [{', '.join(tags)}]\n"
        f"created_at: {created}\n"
        "---\n"
        f"body of {name}\n",
        encoding="utf-8",
    )


def _build_tree(root):
    """复刻 memory_tags.init_tree 的建树逻辑（从真实卡片文件）。"""
    mems = memory_tags.load_all_memories(root)
    ordered = sorted(mems, key=lambda m: m.created_at)
    tree = MemorySegTree(root)
    tree.cards = [m.name for m in ordered]
    tree.card_dates = [memory_tags._parse_date(m.created_at) for m in ordered]
    tree.build()
    return tree


class TestSaveLoadRoundtrip:
    def test_persist_reload_queries(self, tmp_path):
        _seed_card(tmp_path, "distributed-lock", "三种实现", ["并发", "锁"], "2026-01-01")
        _seed_card(tmp_path, "sqlite-vs-mysql", "选型对比", ["数据库"], "2026-02-01")

        tree = _build_tree(tmp_path)
        tree.force_summarize_all()  # 模板摘要（确定性，零 LLM）
        assert tree.root.summary, "根摘要应非空"
        tree.save()
        segments = tmp_path / ".mai" / "memory" / "segments.json"
        assert segments.exists()

        # 新实例 load——验证摘要/结构/查询都从磁盘恢复
        t2 = MemorySegTree(tmp_path)
        assert t2.load()
        assert t2.cards == ["distributed-lock", "sqlite-vs-mysql"]
        assert t2.root.summary == tree.root.summary
        assert t2.query_by_tag("并发") == ["distributed-lock"]
        assert t2.query_by_tag("数据库") == ["sqlite-vs-mysql"]
        # 区间查询：2026-02 之后只有 sqlite-vs-mysql
        got = t2.query_by_daterange(date(2026, 2, 1), date(2026, 12, 31))
        assert got == ["sqlite-vs-mysql"]

    def test_dirty_summary_recomputed_and_saved(self, tmp_path):
        _seed_card(tmp_path, "a", "card a", ["t1"], "2026-01-01")
        tree = _build_tree(tmp_path)
        tree.save()

        # 追加新卡（路径更新会打 dirty）→ 模板摘要后 save
        _seed_card(tmp_path, "b", "card b", ["t2"], "2026-02-01")
        tree2 = _build_tree(tmp_path)  # 模拟引擎重启后从磁盘 load
        tree2.force_summarize_all()
        tree2.save()
        raw = json.loads((tmp_path / ".mai" / "memory" / "segments.json").read_text(encoding="utf-8"))
        assert raw["cards"] == ["a", "b"]


class TestMemoryTagsWiring:
    def test_save_memory_writes_segments_json(self, tmp_path):
        import asyncio
        from pathlib import Path

        async def main():
            return await memory_tags.save_memory(
                memory_tags.TaggedMemory(
                    name="plugin-mem", description="d", tags=["p"],
                    content="c", created_at="2026-03-01",
                ),
                str(tmp_path),
            )

        path = Path(asyncio.run(main()))
        assert path.exists()
        seg = tmp_path / ".mai" / "memory" / "segments.json"
        assert seg.exists(), "save_memory 必须落盘 segments.json（P1-3 接线）"
        data = json.loads(seg.read_text(encoding="utf-8"))
        assert "plugin-mem" in data["cards"]

    def test_delete_memory_updates_segments_json(self, tmp_path):
        async def main():
            import asyncio
            await memory_tags.save_memory(
                memory_tags.TaggedMemory(
                    name="doomed", description="d", tags=["t"],
                    content="c", created_at="2026-03-01",
                ),
                str(tmp_path),
            )
            return await memory_tags.delete_memory("doomed", str(tmp_path))

        import asyncio
        assert asyncio.run(main()) is True
        seg = tmp_path / ".mai" / "memory" / "segments.json"
        data = json.loads(seg.read_text(encoding="utf-8"))
        assert "doomed" not in data["cards"]
