"""H2Mem: Memory Segment Tree — 按时间排序的记忆线段树。

核心思想: 在按时间排序的卡片数组上建立分段树，内部节点存 LLM 摘要，
懒标记 (dirty) 延迟重算，检索时用 topic 集合剪枝。

数据结构:
  SegNode      — 线段树节点（L/R 区间, summary, topics, dirty, 子节点）
  MemorySegTree — 树容器（cards 数组, 建树, 插入, 查询, 序列化）

不变式:
  1. cards 严格按 card_dates 升序
  2. 树 cover [0, len(cards)), 宽度 = next_power_of_2
  3. card_count == R - L
  4. dirty → 子树有未反映到 summary 的变化
  5. topics 是子树所有 tags 的并集
"""

from __future__ import annotations

import bisect
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

SEGMENTS_FILE = ".mai/memory/segments.json"
MAX_BATCH_SHIFTS = 100  # 累积此数量的位移后触发全量重算


# ── SegNode ──────────────────────────────────────────────


@dataclass
class SegNode:
    """线段树节点。叶子节点 left=None and right=None。"""

    L: int                         # 区间左边界（闭）
    R: int                         # 区间右边界（开），R > L
    summary: str = ""              # LLM 摘要（内部节点有值，叶子空）
    topics: set[str] = field(default_factory=set)
    card_count: int = 0            # == R - L（维护用）
    dirty: bool = False            # 懒标记
    earliest_date: Optional[date] = None
    latest_date: Optional[date] = None
    left: Optional["SegNode"] = None
    right: Optional["SegNode"] = None

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None

    @property
    def width(self) -> int:
        return self.R - self.L

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容 dict。"""
        d: dict[str, Any] = {
            "L": self.L, "R": self.R,
            "summary": self.summary,
            "topics": sorted(self.topics),
            "card_count": self.card_count,
            "dirty": self.dirty,
            "earliest_date": self.earliest_date.isoformat() if self.earliest_date else None,
            "latest_date": self.latest_date.isoformat() if self.latest_date else None,
        }
        if self.left is not None:
            d["left"] = self.left.to_dict()
        if self.right is not None:
            d["right"] = self.right.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SegNode":
        """从 JSON dict 反序列化。"""
        node = cls(
            L=d["L"], R=d["R"],
            summary=d.get("summary", ""),
            topics=set(d.get("topics", [])),
            card_count=d.get("card_count", 0),
            dirty=d.get("dirty", False),
            earliest_date=date.fromisoformat(d["earliest_date"]) if d.get("earliest_date") else None,
            latest_date=date.fromisoformat(d["latest_date"]) if d.get("latest_date") else None,
        )
        if "left" in d:
            node.left = cls.from_dict(d["left"])
        if "right" in d:
            node.right = cls.from_dict(d["right"])
        return node


# ── MemorySegTree ────────────────────────────────────────


class MemorySegTree:
    """记忆线段树。

    在 cards[] 数组的下标上建立分段树。
    cards 按 card_dates 升序排列，插入时保持有序。
    """

    def __init__(self, project_root: str = "."):
        self._root_dir = project_root
        self.cards: list[str] = []          # 卡片 name，按时间升序
        self.card_dates: list[date] = []    # 并行数组
        self.root: Optional[SegNode] = None
        self._card_index: dict[str, int] = {}   # name → cards 下标（旧值）
        self._batch_shifts: list[tuple[int, int]] = []  # (pos, +delta)，分块偏移

    # ── 下标查找（含分块偏移） ────────────────────────

    def _real_index(self, name: str) -> Optional[int]:
        """获取卡片的真实当前下标。处理 batch_shifts 偏移。"""
        base = self._card_index.get(name)
        if base is None:
            return None
        idx = base
        for pos, delta in self._batch_shifts:
            if idx >= pos:
                idx += delta
        return idx

    def _all_real_indices(self) -> dict[str, int]:
        """重算全部卡片的真实下标（压缩 batch_shifts）。"""
        result: dict[str, int] = {}
        for i, name in enumerate(self.cards):
            result[name] = i
        self._card_index = result
        self._batch_shifts.clear()
        return result

    # ── 建树 ───────────────────────────────────────────

    def build(self) -> None:
        """自底向上构建线段树。O(n)。

        前置: self.cards 和 self.card_dates 已填充并排序。
        如果 .mai/memory/segments.json 不存在或损坏，调用此方法从零建树。
        """
        n = len(self.cards)
        if n == 0:
            self.root = None
            return

        # 补齐到 2 的幂
        padded_n = 1 << (n - 1).bit_length() if n > 1 else 1

        # 构建叶子层
        leaves: list[SegNode] = []
        for i in range(padded_n):
            if i < n:
                # 从卡片文件读取 topics
                topics = self._read_card_topics(self.cards[i])
                leaf = SegNode(
                    L=i, R=i + 1,
                    topics=topics,
                    card_count=1,
                    earliest_date=self.card_dates[i],
                    latest_date=self.card_dates[i],
                )
            else:
                leaf = SegNode(L=i, R=i + 1, card_count=0)  # 虚拟节点
            leaves.append(leaf)

        # 逐层合并
        current = leaves
        while len(current) > 1:
            next_level: list[SegNode] = []
            for i in range(0, len(current), 2):
                left = current[i]
                right = current[i + 1] if i + 1 < len(current) else None

                if right is None or right.card_count == 0:
                    # 只有左子有实际内容，直接提升左子
                    next_level.append(left)
                    continue

                earliest = left.earliest_date
                if right.earliest_date and (not earliest or right.earliest_date < earliest):
                    earliest = right.earliest_date
                latest = left.latest_date
                if right.latest_date and (not latest or right.latest_date > latest):
                    latest = right.latest_date

                parent = SegNode(
                    L=left.L, R=right.R,
                    topics=left.topics | right.topics,
                    card_count=left.card_count + right.card_count,
                    dirty=True,  # 新建，需要 LLM 生成摘要
                    earliest_date=earliest,
                    latest_date=latest,
                    left=left, right=right,
                )
                next_level.append(parent)
            current = next_level

        self.root = current[0]

        # 构建 card_index
        for i, name in enumerate(self.cards):
            self._card_index[name] = i
        self._batch_shifts.clear()

    # ── 插入 ───────────────────────────────────────────

    def insert(self, name: str, card_date: date, description: str,
               topics: Optional[list[str]] = None) -> int:
        """插入一张卡片。O(log n + batch_size)。

        Args:
            name: 卡片名（kebab-case，全局唯一）
            card_date: 卡片日期
            description: 一句话描述（用于摘要生成）
            topics: 标签列表

        Returns:
            插入位置的下标。

        Raises:
            ValueError: name 已存在
        """
        if name in self._card_index:
            raise ValueError(f"卡片已存在: {name}")

        topics = topics or []
        topic_set = set(topics)

        # 1. 二分查找插入位置
        pos = bisect.bisect_right(self.card_dates, card_date)
        self.cards.insert(pos, name)
        self.card_dates.insert(pos, card_date)

        # 2. 记录分块偏移（延迟 O(n) 全量更新）
        self._batch_shifts.append((pos, 1))
        self._card_index[name] = pos  # 插入时的临时下标

        # 3. 树扩展检查
        rebuilt = False
        if self.root is None:
            self.build()
            return pos
        if len(self.cards) > self.root.R:
            self._expand_tree()
            rebuilt = True  # build() 已重建整棵树，card 已计入

        # 4. 从叶子向上打 dirty 标记（仅当树未被重建时——重建后子树已 dirty）
        if not rebuilt and self.root:
            self._dirty_path(pos, topic_set, card_date)

        # 5. batch_shifts 超阈值 → 压缩
        if len(self._batch_shifts) >= MAX_BATCH_SHIFTS:
            self._all_real_indices()
            # 树需要重建（因为旧的叶子下标全乱了）
            self.build()

        return pos

    def _expand_tree(self) -> None:
        """扩容树到 next_power_of_2(len(cards))。"""
        new_n = 1 << (len(self.cards) - 1).bit_length() if len(self.cards) > 1 else 1
        if self.root and new_n <= self.root.R:
            return  # 不需要扩容

        # 当前树可能不是满的——重建最简单且正确
        self.build()

    def _dirty_path(self, pos: int, topics: set[str], card_date: date) -> None:
        """从根向下走到 pos 的路径，沿途更新 card_count/dirty/topics/日期范围。

        插入后树的 L/R 已在 insert 前通过 _expand_tree 保证覆盖 pos，
        但从根向下找需要不用旧叶子——直接用根遍历。
        """
        if self.root is None:
            return
        self._dirty_from_root(self.root, pos, topics, card_date)

    def _dirty_from_root(self, node: SegNode, pos: int, topics: set[str],
                         card_date: date) -> None:
        """从根向下找到覆盖 pos 的路径，更新祖先。"""
        if node.L > pos or node.R <= pos:
            return  # 不在当前节点范围内
        node.card_count += 1
        node.topics |= topics
        node.dirty = True
        if node.earliest_date is None or card_date < node.earliest_date:
            node.earliest_date = card_date
        if node.latest_date is None or card_date > node.latest_date:
            node.latest_date = card_date

        if node.is_leaf:
            return
        if node.left:
            self._dirty_from_root(node.left, pos, topics, card_date)
        if node.right:
            self._dirty_from_root(node.right, pos, topics, card_date)

    # ── 删除 ───────────────────────────────────────────

    def remove(self, name: str) -> bool:
        """删除一张卡片。O(log n)。"""
        idx = self._real_index(name)
        if idx is None:
            # 尝试用当前 cards 数组线性查（退化路径）
            try:
                idx = self.cards.index(name)
            except ValueError:
                return False

        del self.cards[idx]
        del self.card_dates[idx]
        self._card_index.pop(name, None)
        self._batch_shifts.append((idx, -1))

        # 树重建是最可靠的方式
        if len(self._batch_shifts) >= MAX_BATCH_SHIFTS:
            self._all_real_indices()
        self.build()
        return True

    # ── 查询 ───────────────────────────────────────────

    def query_by_tag(self, tag: str, max_results: int = 50) -> list[str]:
        """按标签检索卡片。O(log n + k)，k = 命中数。

        用内部节点的 topics 集合做剪枝：子树不含目标 tag → 整枝跳过。
        """
        if self.root is None or tag not in self.root.topics:
            return []

        results: list[str] = []
        self._query_tag(self.root, tag, results, max_results)
        return results

    def _query_tag(self, node: SegNode, tag: str, results: list[str],
                   max_results: int) -> None:
        """递归 tag 查询，含 topics 剪枝。"""
        if len(results) >= max_results:
            return
        if tag not in node.topics:
            return  # 剪枝
        if node.is_leaf:
            if node.card_count == 0:
                return  # 虚拟叶子
            # 叶子验证——读卡片文件确认 tag 确实存在
            card_name = self._card_name_at(node.L)
            if card_name and self._card_has_tag(card_name, tag):
                results.append(card_name)
            return
        # 内部节点：先左后右（时间升序）
        if node.left:
            self._query_tag(node.left, tag, results, max_results)
        if node.right:
            self._query_tag(node.right, tag, results, max_results)

    def query_by_daterange(self, start: date, end: date, tag: Optional[str] = None,
                           max_results: int = 50) -> list[str]:
        """区间查询：[start, end] 时间范围内的卡片。O(log n + k)。

        Args:
            start: 起始日期（包含）
            end: 结束日期（包含）
            tag: 可选标签过滤
            max_results: 最多返回条数
        """
        if self.root is None:
            return []
        results: list[str] = []
        self._query_range(self.root, start, end, tag, results, max_results)
        return results

    def _query_range(self, node: SegNode, start: date, end: date,
                     tag: Optional[str], results: list[str],
                     max_results: int) -> None:
        """递归区间查询，含时间 + 标签双重剪枝。"""
        if len(results) >= max_results:
            return
        # 时间剪枝
        if node.latest_date and node.latest_date < start:
            return
        if node.earliest_date and node.earliest_date > end:
            return
        # 标签剪枝
        if tag and tag not in node.topics:
            return

        if node.is_leaf:
            if node.card_count == 0:
                return
            card_name = self._card_name_at(node.L)
            if card_name is None:
                return
            card_date = self._card_date_at(node.L)
            if card_date and start <= card_date <= end:
                if tag is None or self._card_has_tag(card_name, tag):
                    results.append(card_name)
            return

        # 内部节点：先左后右（时间升序）
        if node.left:
            self._query_range(node.left, start, end, tag, results, max_results)
        if node.right:
            self._query_range(node.right, start, end, tag, results, max_results)

    def fuzzy_search(self, keyword: str, max_results: int = 30) -> list[str]:
        """全文模糊检索——在 name + description 中匹配关键词。

        退化为线性扫描（带简单索引加速：仅扫 topics 包含相关分词的子树）。
        """
        results: list[str] = []
        kw = keyword.lower()
        for name in self.cards:
            if self._card_matches(name, kw):
                results.append(name)
                if len(results) >= max_results:
                    break
        return results

    def recent_topics(self, months: int = 3, max_topics: int = 8) -> list[str]:
        """最近 months 个月内的活跃主题（按卡片数排序）。"""
        from datetime import date as _date, timedelta
        cutoff = _date.today() - timedelta(days=months * 30)
        topic_counts: dict[str, int] = {}
        for i, d in enumerate(self.card_dates):
            if d >= cutoff:
                name = self.cards[i]
                card = self._load_card(name)
                if card:
                    for t in card.tags:
                        topic_counts[t] = topic_counts.get(t, 0) + 1
        sorted_topics = sorted(topic_counts.items(), key=lambda x: -x[1])
        return [t for t, _ in sorted_topics[:max_topics]]

    # ── 懒标记下推 ──────────────────────────────────────

    def _push_down(self, node: SegNode) -> None:
        """懒标记下推——用子树信息重新生成摘要。

        Phase 2: 模板拼接（不调 LLM）。
        Phase 3: 将 _merge_summaries 替换为 LLM 调用。
        """
        if not node.dirty or node.is_leaf:
            return
        # 确保子节点是干净的
        if node.left and node.left.dirty and not node.left.is_leaf:
            self._push_down(node.left)
        if node.right and node.right.dirty and not node.right.is_leaf:
            self._push_down(node.right)
        # 合并摘要
        node.summary = self._merge_summaries(node.left, node.right)
        node.dirty = False

    def _merge_summaries(self, left: Optional[SegNode],
                         right: Optional[SegNode]) -> str:
        """合并两个子节点的摘要（模板版，Phase 3 升级为 LLM）。"""
        parts: list[str] = []
        if left and left.summary:
            parts.append(left.summary)
        elif left and left.card_count > 0:
            # 没有摘要 → 列出卡片标题
            names = self._card_names_in_range(left.L, left.R, max_items=3)
            parts.append(", ".join(names))
        if right and right.summary:
            parts.append(right.summary)
        elif right and right.card_count > 0:
            names = self._card_names_in_range(right.L, right.R, max_items=3)
            parts.append(", ".join(names))
        if not parts:
            return "(空)"
        return "；".join(parts)

    def force_summarize_all(self) -> int:
        """遍历树，下推所有 dirty 节点（模板摘要）。返回下推的节点数。"""
        count = 0
        if self.root:
            count = self._summarize_recursive(self.root)
        return count

    async def force_summarize_all_async(self, llm=None) -> int:
        """遍历树，下推所有 dirty 节点（LLM 摘要）。返回下推的节点数。"""
        count = 0
        if self.root:
            count = await self._summarize_recursive_async(self.root, llm)
        return count

    async def summarize_dirty_background(self, llm, max_nodes: int = 10) -> int:
        """后台任务：扫描 dirty 节点，逐个用 LLM 下推。

        Args:
            llm: LLMClient 实例
            max_nodes: 单次最多处理的节点数（防止后台任务跑太久）

        Returns:
            本次处理的节点数
        """
        if self.root is None:
            return 0
        # 收集所有 dirty 内部节点（BFS，优先处理高层节点）
        dirty_nodes = self._collect_dirty(self.root)
        count = 0
        for node in dirty_nodes[:max_nodes]:
            await self._push_down_async(node, llm)
            count += 1
        return count

    def _summarize_recursive(self, node: SegNode) -> int:
        count = 0
        if node.dirty and not node.is_leaf:
            self._push_down(node)
            count += 1
        if node.left:
            count += self._summarize_recursive(node.left)
        if node.right:
            count += self._summarize_recursive(node.right)
        return count

    async def _summarize_recursive_async(self, node: SegNode, llm) -> int:
        count = 0
        if node.dirty and not node.is_leaf:
            await self._push_down_async(node, llm)
            count += 1
        if node.left:
            count += await self._summarize_recursive_async(node.left, llm)
        if node.right:
            count += await self._summarize_recursive_async(node.right, llm)
        return count

    async def _push_down_async(self, node: SegNode, llm) -> None:
        """LLM 版懒标记下推。"""
        if not node.dirty or node.is_leaf:
            return
        if node.left and node.left.dirty and not node.left.is_leaf:
            await self._push_down_async(node.left, llm)
        if node.right and node.right.dirty and not node.right.is_leaf:
            await self._push_down_async(node.right, llm)
        # 调 LLM 合并摘要
        node.summary = await self._merge_summaries_llm(node.left, node.right, llm)
        node.dirty = False

    async def _merge_summaries_llm(self, left: Optional[SegNode],
                                   right: Optional[SegNode], llm) -> str:
        """调 LLM 合并两个子树的摘要为一句话。"""
        # 收集左右子树信息
        left_info = self._node_info(left)
        right_info = self._node_info(right)

        if not left_info and not right_info:
            return "(空)"
        if not left_info:
            return right_info
        if not right_info:
            return left_info

        prompt = (
            "将以下两个时间段的技术学习摘要合并为一句中文摘要（30字以内），"
            "提炼共同主题，保留关键术语:\n"
            f"左: {left_info}\n"
            f"右: {right_info}"
        )
        try:
            msgs = [{"role": "user", "content": prompt}]
            if hasattr(llm, "chat") and callable(llm.chat):
                response = await llm.chat(msgs, temperature=0.0, max_tokens=80)
                return (response.content or "").strip()
            else:
                # 无 LLM 可用，退化为模板拼接
                return f"{left_info}；{right_info}"
        except Exception as exc:
            logger.warning("LLM 摘要合并失败: %s，退化为模板拼接", exc)
            return f"{left_info}；{right_info}"

    @staticmethod
    def _node_info(node: Optional[SegNode]) -> str:
        """获取节点的一句话信息。"""
        if node is None or node.card_count == 0:
            return ""
        date_range = ""
        if node.earliest_date and node.latest_date:
            if node.earliest_date == node.latest_date:
                date_range = node.earliest_date.strftime("%Y-%m")
            else:
                date_range = (
                    f"{node.earliest_date.strftime('%Y-%m')}~"
                    f"{node.latest_date.strftime('%Y-%m')}"
                )
        topics = ", ".join(sorted(node.topics)[:5]) if node.topics else ""
        parts = [f"[{date_range}]" if date_range else ""]
        if topics:
            parts.append(f"主题: {topics}")
        if node.summary:
            parts.append(node.summary)
        return " ".join(p for p in parts if p)

    @staticmethod
    def _collect_dirty(node: SegNode) -> list[SegNode]:
        """BFS 收集所有 dirty 内部节点（浅层优先）。"""
        result: list[SegNode] = []
        queue = [node]
        while queue:
            n = queue.pop(0)
            if n.dirty and not n.is_leaf:
                result.append(n)
            if n.left:
                queue.append(n.left)
            if n.right:
                queue.append(n.right)
        return result

    # ── 辅助 ───────────────────────────────────────────

    def _card_name_at(self, idx: int) -> Optional[str]:
        """安全获取 cards[idx]（考虑虚拟节点越界）。"""
        if 0 <= idx < len(self.cards):
            return self.cards[idx]
        return None

    def _card_date_at(self, idx: int) -> Optional[date]:
        if 0 <= idx < len(self.card_dates):
            return self.card_dates[idx]
        return None

    def _card_has_tag(self, name: str, tag: str) -> bool:
        """检查卡片是否包含标签（读文件验证）。"""
        card = self._load_card(name)
        return tag in card.tags if card else False

    def _card_matches(self, name: str, keyword: str) -> bool:
        """检查卡片 name/description 是否包含关键词。"""
        card = self._load_card(name)
        if card:
            return (keyword in card.name.lower()
                    or keyword in card.description.lower()
                    or keyword in card.content.lower())
        return False

    def _load_card(self, name: str):
        """加载卡片对象（使用树的项目根目录）。"""
        from mai_agent.services.memory_tags import load_memory_by_name
        return load_memory_by_name(name, self._root_dir)

    def _card_names_in_range(self, L: int, R: int, max_items: int = 3) -> list[str]:
        """获取 [L, R) 范围内的卡片名（最多 max_items 个）。"""
        names: list[str] = []
        for i in range(L, min(R, len(self.cards))):
            names.append(self.cards[i])
            if len(names) >= max_items:
                break
        return names

    # ── 序列化 ─────────────────────────────────────────

    @property
    def segments_path(self) -> Path:
        return Path(self._root_dir) / SEGMENTS_FILE

    def dump_state(self) -> dict[str, Any]:
        """导出完整状态为可序列化 dict。"""
        return {
            "cards": self.cards,
            "card_dates": [d.isoformat() for d in self.card_dates],
            "tree": self.root.to_dict() if self.root else None,
        }

    def save(self) -> None:
        """持久化到 .mai/memory/segments.json。"""
        state = self.dump_state()
        self.segments_path.parent.mkdir(parents=True, exist_ok=True)
        self.segments_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> bool:
        """从 segments.json 加载。成功返回 True，文件不存在/损坏返回 False。"""
        path = self.segments_path
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.cards = data.get("cards", [])
            self.card_dates = [date.fromisoformat(d) for d in data.get("card_dates", [])]
            if data.get("tree"):
                self.root = SegNode.from_dict(data["tree"])
            # 重建 card_index
            for i, name in enumerate(self.cards):
                self._card_index[name] = i
            self._batch_shifts.clear()
            return True
        except Exception as exc:
            logger.warning("segments.json 加载失败: %s", exc)
            return False

    # ── 一致性检查 ─────────────────────────────────────

    def verify(self) -> list[str]:
        """检查树的不变量。返回错误列表，空 = 一致。"""
        errors: list[str] = []
        if self.root is None:
            if len(self.cards) == 0:
                return errors
            errors.append("cards 非空但 root 为 None")
            return errors

        # 检查 root cover 范围
        if self.root.L != 0:
            errors.append(f"root.L={self.root.L} 应为 0")
        if self.root.R < len(self.cards):
            errors.append(f"root.R={self.root.R} < len(cards)={len(self.cards)}")

        # 递归检查每个节点
        def _check(node: SegNode, depth: int = 0) -> None:
            actual_cards = node.R - node.L
            if node.card_count != actual_cards:
                errors.append(
                    f"节点 [{node.L},{node.R}) card_count={node.card_count} "
                    f"!= R-L={actual_cards}"
                )
            if node.is_leaf:
                return
            if node.left is None or node.right is None:
                errors.append(f"非叶节点 [{node.L},{node.R}) 缺少子节点")
                return
            if node.left.R != node.right.L:
                errors.append(
                    f"节点 [{node.L},{node.R}) 子节点边界不连续: "
                    f"left.R={node.left.R}, right.L={node.right.L}"
                )
            _check(node.left, depth + 1)
            _check(node.right, depth + 1)

        _check(self.root)
        return errors

    # ── 辅助 ───────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.cards)

    def _read_card_topics(self, name: str) -> set[str]:
        """从 .mai/memory/<name>.md 读取卡片的 tags。"""
        from mai_agent.services.memory_tags import load_memory_by_name
        card = load_memory_by_name(name, self._root_dir)
        if card:
            return set(card.tags)
        return set()
