"""Tests for MemorySegTree — Phase 1: build, insert, serialize, verify."""

import json
import os
from datetime import date

import pytest

from mai_agent.services.memory_segtree import MemorySegTree, SegNode


# ── helpers ──────────────────────────────────────────────


def _setup_cards(temp_dir: str, cards_data: list[tuple[str, str, list[str]]]):
    """Create .mai/memory/<name>.md files for the tree to read topics from.

    Args:
        temp_dir: root dir
        cards_data: list of (name, description, tags)
    """
    mem_dir = os.path.join(temp_dir, ".mai", "memory")
    os.makedirs(mem_dir, exist_ok=True)
    for name, desc, tags in cards_data:
        tags_line = ", ".join(tags)
        content = f"""---
name: {name}
description: {desc}
type: reference
tags: [{tags_line}]
---

# {name}

{desc}
"""
        with open(os.path.join(mem_dir, f"{name}.md"), "w", encoding="utf-8") as f:
            f.write(content)


# ── build tests ───────────────────────────────────────────


def test_build_empty():
    tree = MemorySegTree()
    tree.build()
    assert tree.root is None
    assert tree.cards == []


def test_build_single(temp_dir):
    _setup_cards(temp_dir, [("a", "alpha", ["x"])])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a"]
    tree.card_dates = [date(2026, 8, 1)]
    tree.build()

    assert tree.root is not None
    assert tree.root.is_leaf
    assert tree.root.card_count == 1
    assert tree.root.topics == {"x"}
    assert tree.root.L == 0
    assert tree.root.R == 1
    assert tree.root.earliest_date == date(2026, 8, 1)
    assert tree.root.latest_date == date(2026, 8, 1)


def test_build_4_power_of_two(temp_dir):
    _setup_cards(temp_dir, [
        ("a", "alpha", ["x"]),
        ("b", "beta", ["y"]),
        ("c", "gamma", ["x", "z"]),
        ("d", "delta", ["z"]),
    ])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a", "b", "c", "d"]
    tree.card_dates = [
        date(2026, 1, 1), date(2026, 4, 1),
        date(2026, 7, 1), date(2026, 8, 1),
    ]
    tree.build()

    assert tree.root is not None
    assert not tree.root.is_leaf
    assert tree.root.card_count == 4
    assert tree.root.topics == {"x", "y", "z"}
    assert tree.root.L == 0
    assert tree.root.R == 4
    assert tree.root.earliest_date == date(2026, 1, 1)
    assert tree.root.latest_date == date(2026, 8, 1)
    # root should have left and right
    assert tree.root.left is not None
    assert tree.root.right is not None
    # left subtree: cards 0-2
    assert tree.root.left.card_count == 2
    # right subtree: cards 2-4
    assert tree.root.right.card_count == 2


def test_build_5_non_power_of_two(temp_dir):
    """5 cards: tree covers exact range [0,5), virtual nodes collapsed."""
    _setup_cards(temp_dir, [
        ("a", "a", ["t1"]),
        ("b", "b", ["t1"]),
        ("c", "c", ["t2"]),
        ("d", "d", ["t2"]),
        ("e", "e", ["t3"]),
    ])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a", "b", "c", "d", "e"]
    tree.card_dates = [date(2026, i, 1) for i in range(1, 6)]
    tree.build()

    assert tree.root is not None
    assert tree.root.card_count == 5
    assert tree.root.R == 8  # padded to next power of two; [5,8) 为虚拟叶子


def test_build_all_nodes_dirty(temp_dir):
    """Freshly built tree has all internal nodes dirty=True (summaries needed)."""
    _setup_cards(temp_dir, [
        ("a", "a", ["t"]), ("b", "b", ["t"]),
    ])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a", "b"]
    tree.card_dates = [date(2026, 1, 1), date(2026, 2, 1)]
    tree.build()

    # root is internal, should be dirty
    assert tree.root.dirty
    # leaves should NOT be dirty (no summary to generate)
    assert not tree.root.left.dirty
    assert not tree.root.right.dirty


# ── insert tests ────────────────────────────────────────


def test_insert_into_empty(temp_dir):
    _setup_cards(temp_dir, [("a", "alpha", ["x"])])
    tree = MemorySegTree(temp_dir)
    pos = tree.insert("a", date(2026, 8, 9), "alpha", ["x"])

    assert pos == 0
    assert tree.cards == ["a"]
    assert len(tree) == 1


def test_insert_maintains_order(temp_dir):
    _setup_cards(temp_dir, [
        ("a", "jan", ["t1"]),
        ("b", "mar", ["t2"]),
        ("c", "feb", ["t3"]),  # 插入到 jan 和 mar 之间
    ])
    tree = MemorySegTree(temp_dir)

    tree.insert("a", date(2026, 1, 1), "jan", ["t1"])
    tree.insert("b", date(2026, 3, 1), "mar", ["t2"])
    pos = tree.insert("c", date(2026, 2, 1), "feb", ["t3"])

    assert pos == 1  # between a and b
    assert tree.cards == ["a", "c", "b"]
    assert tree._card_index["a"] == 0
    assert tree._card_index["c"] == 1
    assert tree._card_index["b"] == 2


def test_insert_triggers_expansion(temp_dir):
    """Insert beyond current tree width triggers rebuild."""
    _setup_cards(temp_dir, [("a", "a", ["t"])])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a"]
    tree.card_dates = [date(2026, 1, 1)]
    tree.build()
    old_R = tree.root.R  # 1 (padded from 1)
    assert old_R == 1

    _setup_cards(temp_dir, [("a", "a", ["t"]), ("b", "b", ["t"])])
    tree.insert("b", date(2026, 2, 1), "b", ["t"])

    # after insert with rebuild, root covers both cards
    assert tree.root.R >= 2
    assert tree.root.card_count == 2
    assert len(tree) == 2


def test_insert_dirty_path(temp_dir):
    """Insert should mark ancestor nodes dirty."""
    _setup_cards(temp_dir, [
        ("a", "a", ["x"]), ("b", "b", ["y"]),
        ("c", "c", ["z"]), ("d", "d", ["w"]),
    ])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a", "b", "c", "d"]
    tree.card_dates = [date(2026, i, 1) for i in range(1, 5)]
    tree.build()
    # Clear all dirty flags (simulating that summaries were generated)
    _clear_dirty(tree.root)

    _setup_cards(temp_dir, [
        ("a", "a", ["x"]), ("b", "b", ["y"]),
        ("c", "c", ["z"]), ("d", "d", ["w"]),
        ("e", "e", ["new"]),
    ])
    tree.insert("e", date(2026, 5, 1), "e", ["new"])

    # Root should be dirty
    assert tree.root.dirty
    # At least one ancestor on the path should be dirty
    assert _any_dirty_on_path(tree.root, 4)


def _clear_dirty(node: SegNode) -> None:
    node.dirty = False
    if node.left:
        _clear_dirty(node.left)
    if node.right:
        _clear_dirty(node.right)


def _any_dirty_on_path(node: SegNode, pos: int) -> bool:
    """Check if any node on the path to pos is dirty."""
    if node.L > pos or node.R <= pos:
        return False  # pos not in this subtree — shouldn't happen
    found = node.dirty
    if node.is_leaf:
        return found
    if node.left and pos < node.left.R:
        found = found or _any_dirty_on_path(node.left, pos)
    elif node.right:
        found = found or _any_dirty_on_path(node.right, pos)
    return found


# ── serialize tests ──────────────────────────────────────


def test_dump_load_roundtrip(temp_dir):
    _setup_cards(temp_dir, [
        ("a", "alpha", ["x"]),
        ("b", "beta", ["y"]),
        ("c", "gamma", ["x", "z"]),
    ])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a", "b", "c"]
    tree.card_dates = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    tree.build()

    # Set some summary to verify it persists
    tree.root.summary = "test root summary"
    tree.root.dirty = False

    tree.save()
    assert tree.segments_path.exists()

    # Load into new tree
    tree2 = MemorySegTree(temp_dir)
    assert tree2.load()
    assert tree2.cards == ["a", "b", "c"]
    assert tree2.root is not None
    assert tree2.root.card_count == 3
    assert tree2.root.summary == "test root summary"
    assert tree2.root.topics == {"x", "y", "z"}


def test_load_nonexistent():
    tree = MemorySegTree("/nonexistent/path")
    assert not tree.load()


def test_load_corrupted(temp_dir):
    path = os.path.join(temp_dir, ".mai", "memory", "segments.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("not json")
    tree = MemorySegTree(temp_dir)
    assert not tree.load()  # should log warning, return False


# ── verify tests ────────────────────────────────────────


def test_verify_clean_tree_pass(temp_dir):
    _setup_cards(temp_dir, [
        ("a", "a", ["t"]), ("b", "b", ["t"]),
    ])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a", "b"]
    tree.card_dates = [date(2026, 1, 1), date(2026, 2, 1)]
    tree.build()
    errors = tree.verify()
    assert errors == []


def test_verify_empty():
    tree = MemorySegTree()
    errors = tree.verify()
    assert errors == []


def test_verify_card_count_mismatch():
    tree = MemorySegTree()
    tree.cards = ["a"]
    tree.card_dates = [date(2026, 1, 1)]
    tree.build()
    # Deliberately break invariant
    tree.root.card_count = 99
    errors = tree.verify()
    assert len(errors) >= 1
    assert "card_count" in errors[0].lower()


# ── remove tests ────────────────────────────────────────


def test_remove_existing(temp_dir):
    _setup_cards(temp_dir, [
        ("a", "a", ["t"]), ("b", "b", ["t"]), ("c", "c", ["t"]),
    ])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a", "b", "c"]
    tree.card_dates = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    tree.build()

    assert tree.remove("b")
    assert tree.cards == ["a", "c"]
    assert tree.root.card_count == 2


def test_remove_nonexistent(temp_dir):
    tree = MemorySegTree(temp_dir)
    assert not tree.remove("nonexistent")


def test_remove_rebuilds_index(temp_dir):
    """After remove, card_index is consistent with new positions."""
    _setup_cards(temp_dir, [
        ("a", "a", ["t"]), ("b", "b", ["t"]), ("c", "c", ["t"]),
    ])
    tree = MemorySegTree(temp_dir)
    tree.cards = ["a", "b", "c"]
    tree.card_dates = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    tree.build()

    tree.remove("b")
    # Card indices should be correct after remove triggers rebuild
    assert tree._card_index["a"] == 0
    assert tree._card_index["c"] == 1


# ── Phase 2: query tests ────────────────────────────────


def _make_tree(temp_dir, cards_spec):
    """Helper: create tree from cards_spec = [(name, date, tags), ...]."""
    _setup_cards(temp_dir, [(n, n, tags) for n, _, tags in cards_spec])
    tree = MemorySegTree(temp_dir)
    tree.cards = [n for n, _, _ in cards_spec]
    tree.card_dates = [d for _, d, _ in cards_spec]
    tree.build()
    return tree


def test_query_by_tag_hit(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["rust"]),
        ("b", date(2026, 2, 1), ["rust", "async"]),
        ("c", date(2026, 3, 1), ["python"]),
    ])
    results = tree.query_by_tag("rust")
    assert sorted(results) == ["a", "b"]


def test_query_by_tag_miss(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["rust"]),
    ])
    results = tree.query_by_tag("nonexistent")
    assert results == []


def test_query_by_tag_prune_uses_topics(temp_dir):
    """Verify that a subtree without the tag is pruned (topics check)."""
    tree = _make_tree(temp_dir, [
        ("left_card", date(2026, 1, 1), ["rust"]),
        ("right_card", date(2026, 7, 1), ["python"]),
    ])
    # Root has topics {"rust", "python"}. Left subtree only "rust", right only "python".
    results = tree.query_by_tag("rust")
    assert results == ["left_card"]
    # Python tag should only find right_card
    results_py = tree.query_by_tag("python")
    assert results_py == ["right_card"]


def test_query_daterange(temp_dir):
    tree = _make_tree(temp_dir, [
        ("jan", date(2026, 1, 1), ["x"]),
        ("feb", date(2026, 2, 1), ["x"]),
        ("mar", date(2026, 3, 1), ["x"]),
        ("apr", date(2026, 4, 1), ["x"]),
    ])
    results = tree.query_by_daterange(date(2026, 2, 1), date(2026, 3, 1))
    assert sorted(results) == ["feb", "mar"]


def test_query_daterange_with_tag(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["t1"]),
        ("b", date(2026, 2, 1), ["t2"]),
        ("c", date(2026, 3, 1), ["t1"]),
    ])
    results = tree.query_by_daterange(
        date(2026, 1, 1), date(2026, 3, 1), tag="t1",
    )
    assert sorted(results) == ["a", "c"]


def test_query_daterange_none_in_range(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["x"]),
    ])
    results = tree.query_by_daterange(date(2025, 1, 1), date(2025, 12, 31))
    assert results == []


def test_fuzzy_search(temp_dir):
    _setup_cards(temp_dir, [
        ("redis", "Redis 缓存策略", ["db"]),
        ("rust-async", "Rust 异步运行时", ["rust"]),
        ("k8s", "Kubernetes 部署", ["devops"]),
    ])
    tree = _make_tree(temp_dir, [
        ("redis", date(2026, 1, 1), ["db"]),
        ("rust-async", date(2026, 2, 1), ["rust"]),
        ("k8s", date(2026, 3, 1), ["devops"]),
    ])
    results = tree.fuzzy_search("redis")
    assert results == ["redis"]
    results2 = tree.fuzzy_search("nonexistent")
    assert results2 == []


def test_push_down_merges_summaries(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["x"]),
        ("b", date(2026, 2, 1), ["y"]),
    ])
    # Initially dirty
    assert tree.root.dirty
    tree._push_down(tree.root)
    assert not tree.root.dirty
    # Summary should contain both card names
    assert "a" in tree.root.summary
    assert "b" in tree.root.summary


def test_force_summarize_all(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["x"]),
        ("b", date(2026, 2, 1), ["y"]),
        ("c", date(2026, 3, 1), ["z"]),
    ])
    count = tree.force_summarize_all()
    assert count >= 1  # at least root was summarized
    assert not tree.root.dirty
    # All internal nodes should be clean
    assert _all_clean(tree.root)


def _all_clean(node) -> bool:
    if node.dirty:
        return False
    if node.left and not _all_clean(node.left):
        return False
    if node.right and not _all_clean(node.right):
        return False
    return True


def test_push_down_preserves_card_count(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["x"]),
        ("b", date(2026, 2, 1), ["y"]),
    ])
    old_count = tree.root.card_count
    tree._push_down(tree.root)
    assert tree.root.card_count == old_count


def test_recent_topics(temp_dir):
    from datetime import date as _date, timedelta
    today = _date.today()
    last_month = today - timedelta(days=20)

    tree = _make_tree(temp_dir, [
        ("a", last_month, ["rust"]),
        ("b", last_month, ["rust", "async"]),
        ("c", date(2024, 1, 1), ["old"]),  # too old
    ])
    topics = tree.recent_topics(months=1)
    assert "rust" in topics
    assert "old" not in topics  # outside recent window


def test_query_after_insert_sees_new_card(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["x"]),
    ])
    _setup_cards(temp_dir, [
        ("a", "a", ["x"]),
        ("b", "b", ["x"]),
    ])
    tree.insert("b", date(2026, 2, 1), "b", ["x"])
    results = tree.query_by_tag("x")
    assert "b" in results


def test_query_empty_tree(temp_dir):
    tree = MemorySegTree(temp_dir)
    assert tree.query_by_tag("x") == []
    assert tree.query_by_daterange(date(2026, 1, 1), date(2026, 12, 31)) == []
    assert tree.fuzzy_search("x") == []
    assert tree.recent_topics() == []


# ── Phase 3: LLM summarization ──────────────────────────


class _MockSummaryLLM:
    """Mock LLM that returns a predictable summary."""
    async def chat(self, messages, temperature=0.0, max_tokens=80, **kw):
        from mai_agent.llm.client import LLMResponse
        return LLMResponse(
            content="Mock 合并摘要: 分布式与Rust",
            tool_calls=None,
            finish_reason="stop",
        )


@pytest.mark.asyncio
async def test_async_summarize_all(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["rust"]),
        ("b", date(2026, 2, 1), ["distributed"]),
    ])
    assert tree.root.dirty
    llm = _MockSummaryLLM()
    count = await tree.force_summarize_all_async(llm)
    assert count >= 1
    assert not tree.root.dirty
    assert "Mock 合并摘要" in tree.root.summary


@pytest.mark.asyncio
async def test_background_summarize_dirty(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["x"]),
        ("b", date(2026, 2, 1), ["y"]),
        ("c", date(2026, 3, 1), ["z"]),
    ])
    # Root is dirty (new build), force its summary
    llm = _MockSummaryLLM()
    processed = await tree.summarize_dirty_background(llm, max_nodes=5)
    assert processed >= 1
    assert not tree.root.dirty


@pytest.mark.asyncio
async def test_async_summarize_falls_back_to_template(temp_dir):
    """If llm is not LLMClient, falls back to template merge."""
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["x"]),
        ("b", date(2026, 2, 1), ["y"]),
    ])
    # Pass a non-LLMClient object → should use template fallback
    count = await tree.force_summarize_all_async(llm="not_a_client")
    assert count >= 1
    assert not tree.root.dirty
    assert tree.root.summary  # non-empty fallback


def test_collect_dirty(temp_dir):
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["x"]),
        ("b", date(2026, 2, 1), ["y"]),
        ("c", date(2026, 3, 1), ["z"]),
    ])
    dirty = MemorySegTree._collect_dirty(tree.root)
    assert len(dirty) >= 1
    assert all(n.dirty and not n.is_leaf for n in dirty)


def test_node_info_empty():
    info = MemorySegTree._node_info(None)
    assert info == ""


def test_node_info_with_date_range(temp_dir):
    """Node spanning multiple dates shows range."""
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 1, 1), ["rust"]),
        ("b", date(2026, 6, 1), ["rust"]),
    ])
    info = MemorySegTree._node_info(tree.root)
    assert "2026-01" in info
    assert "rust" in info


def test_node_info_single_date(temp_dir):
    """Single date node shows just that month."""
    tree = _make_tree(temp_dir, [
        ("a", date(2026, 3, 15), ["python"]),
    ])
    info = MemorySegTree._node_info(tree.root)
    assert "2026-03" in info


def test_randomized_differential():
    """随机对拍：insert/remove 后不变量 + tag/date 查询与朴素暴力一致。

    覆盖追加/中间插入/删除的混合路径，防止 O(log n) 懒更新回归。
    """
    import random
    from datetime import date as _date, timedelta
    from tempfile import TemporaryDirectory

    rng = random.Random(20260811)
    tags_pool = ['redis', 'distributed', 'web', 'rust', 'db', 'k8s']

    with TemporaryDirectory() as tmp:
        tree = MemorySegTree(tmp)
        topics_by_name: dict[str, list[str]] = {}
        # 去磁盘 IO：mock 掉文件读（不改被测树逻辑）
        tree._read_card_topics = lambda name: set(topics_by_name.get(name, set()))
        tree._card_has_tag = lambda name, tag: tag in topics_by_name.get(name, set())

        model: list[dict] = []
        for step in range(500):
            if rng.random() < 0.75 or not model:
                name = f"card{step}"
                if model and rng.random() < 0.85:
                    d = model[-1]['date'] + timedelta(days=rng.randint(0, 30))  # 追加为主
                else:
                    d = _date(2024, 1, 1) + timedelta(days=rng.randint(0, 2000))  # 偶尔中间
                tags = rng.sample(tags_pool, rng.randint(0, 3))
                topics_by_name[name] = tags
                tree.insert(name, d, name, tags)
                model.append({'name': name, 'date': d, 'tags': set(tags)})
                model.sort(key=lambda x: x['date'])
            else:
                victim = rng.choice(model)
                tree.remove(victim['name'])
                model = [m for m in model if m['name'] != victim['name']]

            assert tree.verify() == []
            assert tree.cards == [m['name'] for m in model]
            for tag in tags_pool:
                got = set(tree.query_by_tag(tag, max_results=99999))
                want = {m['name'] for m in model if tag in m['tags']}
                assert got == want, f"step {step} tag={tag} got={got} want={want}"

            if model:
                d1 = _date(2024, 1, 1) + timedelta(days=rng.randint(0, 1500))
                d2 = d1 + timedelta(days=rng.randint(0, 500))
                got = set(tree.query_by_daterange(d1, d2, max_results=99999))
                want = {m['name'] for m in model if d1 <= m['date'] <= d2}
                assert got == want, f"step {step} range got={got} want={want}"
