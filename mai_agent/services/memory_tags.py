"""Tagged Memory 系统 — 对应 Claude Code 的记忆模型。

Claude Code 的记忆系统特征:
  - 每条记忆一个 .md 文件，带 frontmatter (name/description/type/tags)
  - MEMORY.md 作为索引：一行一条 `- [Title](file.md) — hook`
  - `[[name]]` wiki-link 在记忆间建立关联
  - 按 tag / name / type 分类检索

本模块在原有 SESSION_MEMORY.md（自动会话摘要）之上，叠加一个
"标签化记忆卡片"子系统，存放在 .mai/memory/。

两种记忆的关系:
  - SESSION_MEMORY.md : 自动提取的会话流水摘要（时间线）
  - .mai/memory/*.md  : 手动/显式保存的、可标签检索的长期记忆卡片（知识网）

文件格式（单条记忆卡片）::

    ---
    name: distributed-lock
    description: 分布式锁的三种实现与选型
    type: reference        # user | feedback | project | reference
    tags: [分布式, 并发, 后端]
    ---

    正文...可用 [[redis]] 关联其他记忆。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MEMORY_DIR = ".mai/memory"
INDEX_FILE = "MEMORY.md"
TAG_INDEX_FILE = "tags.json"

VALID_TYPES = {"user", "feedback", "project", "reference"}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class TaggedMemory:
    """一条标签化记忆卡片。"""
    name: str
    description: str
    type: str = "reference"  # user | feedback | project | reference
    tags: list[str] = field(default_factory=list)
    content: str = ""
    source_path: str = ""
    created_at: str = ""

    def to_markdown(self) -> str:
        """序列化为带 frontmatter 的 .md。"""
        tags_str = ", ".join(self.tags) if self.tags else ""
        meta = [
            "---",
            f"name: {self.name}",
            f"description: {self.description}",
            f"type: {self.type}",
            f"tags: [{tags_str}]",
            f"created_at: {self.created_at or _now()}",
            "---",
            "",
        ]
        return "\n".join(meta) + self.content.strip() + "\n"

    def index_line(self) -> str:
        """MEMORY.md 索引中的一行。"""
        hook = self.description
        return f"- [{self.name}]({self.name}.md) — {hook}"

    def wiki_links(self) -> list[str]:
        """返回正文中引用的 [[name]] 列表。"""
        return _WIKILINK_RE.findall(self.content)


# ── MemorySegTree 集成 ─────────────────────────────────────

_trees: dict[str, Any] = {}  # resolved project_root → MemorySegTree（多工作区隔离）


def _tree_key(project_root: str) -> str:
    return str(Path(project_root).resolve())


def init_tree(project_root: str = ".") -> Any:
    """初始化某工作区的记忆线段树（尝试加载或从零构建，按工作区缓存）。"""
    key = _tree_key(project_root)
    if key in _trees:
        return _trees[key]
    from mai_agent.services.memory_segtree import MemorySegTree
    tree = MemorySegTree(project_root)
    if not tree.load():
        # segments.json 不存在或损坏 → 从现有卡片构建
        memories = load_all_memories(project_root)
        if memories:
            tree.cards = [m.name for m in sorted(memories, key=lambda m: m.created_at)]
            tree.card_dates = [_parse_date(m.created_at) for m in sorted(memories, key=lambda m: m.created_at)]
            tree.build()
    _trees[key] = tree
    return tree


def _parse_date(s: str) -> Any:
    """安全解析日期字符串。"""
    from datetime import date as _date
    try:
        return _date.fromisoformat(s[:10])
    except Exception:
        return _date.today()


def get_tree(project_root: str = ".", refresh: bool = False) -> Any:
    """获取指定工作区的 MemorySegTree 实例（None 表示不可用）。

    懒初始化: 若该工作区树未建（engine 未启动过 / 其他进程），
    自动 init_tree 建树，保证查询工具无论何时调用都能用上线段树。
    """
    key = _tree_key(project_root)
    tree = _trees.get(key)
    if tree is None:
        try:
            tree = init_tree(project_root)
        except Exception as exc:
            logger.debug("segtree 懒初始化失败: %s", exc)
            return None
    if refresh and tree:
        tree.build()  # 从当前 cards 重建
    return tree


def _maybe_insert_tree(name: str, description: str, tags: list[str],
                       created_at: str, project_root: str = ".") -> None:
    """如果该工作区的 segtree 可用，插入卡片。"""
    tree = get_tree(project_root)
    if tree is None:
        return
    try:
        tree.insert(name, _parse_date(created_at), description, tags)
    except Exception as exc:
        logger.debug("segtree insert 失败: %s", exc)


def _maybe_remove_tree(name: str, project_root: str = ".") -> None:
    """如果该工作区的 segtree 可用，删除卡片。"""
    tree = get_tree(project_root)
    if tree is None:
        return
    try:
        tree.remove(name)
    except Exception as exc:
        logger.debug("segtree remove 失败: %s", exc)


# ── 路径辅助 ──────────────────────────────────────────────


def memory_dir(project_root: str = ".") -> Path:
    return Path(project_root) / MEMORY_DIR


def index_path(project_root: str = ".") -> Path:
    return memory_dir(project_root) / INDEX_FILE


def tag_index_path(project_root: str = ".") -> Path:
    return memory_dir(project_root) / TAG_INDEX_FILE


def _ensure_dir(project_root: str) -> Path:
    d = memory_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── 单条记忆的读写 ────────────────────────────────────────


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_meta, body = match.group(1), match.group(2)
    meta: dict[str, str] = {}
    for line in raw_meta.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, body


def _parse_tags(raw: str) -> list[str]:
    """解析 'tags: [a, b, c]' 的值部分。"""
    cleaned = raw.strip().strip("[]")
    if not cleaned:
        return []
    return [t.strip().strip('"').strip("'") for t in cleaned.split(",") if t.strip()]


def load_memory_by_name(name: str, project_root: str = ".") -> Optional[TaggedMemory]:
    """按 name 加载一条记忆卡片。"""
    path = memory_dir(project_root) / f"{name}.md"
    if not path.exists():
        return None
    return _load_file(path)


def _load_file(path: Path) -> Optional[TaggedMemory]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("读取记忆失败 %s: %s", path, exc)
        return None
    meta, body = _parse_frontmatter(text)
    return TaggedMemory(
        name=meta.get("name", path.stem),
        description=meta.get("description", ""),
        type=meta.get("type", "reference"),
        tags=_parse_tags(meta.get("tags", "")),
        content=body.strip(),
        source_path=str(path),
        created_at=meta.get("created_at", ""),
    )


def load_all_memories(project_root: str = ".") -> list[TaggedMemory]:
    """加载全部记忆卡片。"""
    d = memory_dir(project_root)
    if not d.is_dir():
        return []
    return [m for m in (_load_file(p) for p in sorted(d.glob("*.md")) if p.name != INDEX_FILE) if m]


def save_memory(memory: TaggedMemory, project_root: str = ".") -> str:
    """保存一条记忆卡片，返回其路径。同时刷新索引。"""
    _ensure_dir(project_root)
    if memory.type not in VALID_TYPES:
        memory.type = "reference"
    if not memory.created_at:
        memory.created_at = _now()

    path = memory_dir(project_root) / f"{memory.name}.md"
    path.write_text(memory.to_markdown(), encoding="utf-8")
    memory.source_path = str(path)

    rebuild_index(project_root)
    _maybe_insert_tree(memory.name, memory.description, memory.tags,
                       memory.created_at, project_root)
    # 同步向量索引（语义检索）——失败不阻断主流程
    try:
        from mai_agent.services.memory_vector import index_card
        index_card(memory, project_root)
    except Exception:
        pass
    logger.info("记忆已保存: %s (tags=%s)", memory.name, memory.tags)
    return str(path)


def delete_memory(name: str, project_root: str = ".") -> bool:
    """删除一条记忆卡片。"""
    path = memory_dir(project_root) / f"{name}.md"
    if not path.exists():
        return False
    path.unlink()
    rebuild_index(project_root)
    _maybe_remove_tree(name, project_root)
    # 同步删除向量索引
    try:
        from mai_agent.services.memory_vector import remove_card
        remove_card(name, project_root)
    except Exception:
        pass
    return True


# ── 索引维护 ──────────────────────────────────────────────


def rebuild_index(project_root: str = ".") -> None:
    """重建 MEMORY.md 索引与 tags.json 倒排索引。"""
    _ensure_dir(project_root)
    memories = load_all_memories(project_root)

    # MEMORY.md 索引
    lines = ["# Memory Index", "", "一行一条记忆，自动维护。", ""]
    for m in sorted(memories, key=lambda x: x.name):
        lines.append(m.index_line())
    index_path(project_root).write_text("\n".join(lines) + "\n", encoding="utf-8")

    # tags.json 倒排索引
    tag_index: dict[str, list[str]] = {}
    for m in memories:
        for t in m.tags:
            tag_index.setdefault(t, []).append(m.name)
    tag_index_path(project_root).write_text(
        json.dumps(tag_index, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def load_tag_index(project_root: str = ".") -> dict[str, list[str]]:
    """加载 tag → [names] 倒排索引。"""
    p = tag_index_path(project_root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── 检索 ──────────────────────────────────────────────────


def search_by_tag(tag: str, project_root: str = ".") -> list[TaggedMemory]:
    """按标签检索记忆。优先用 segtree (O(log n))，无树时降级为 tags.json (O(n))。"""
    # 优先 segtree（上限放宽，避免默认 50 静默截断同 tag 大量卡片）
    tree = get_tree(project_root)
    if tree is not None:
        names = tree.query_by_tag(tag, max_results=10000)
        results = [load_memory_by_name(n, project_root) for n in names]
        return [m for m in results if m is not None]

    # 降级：tags.json
    index = load_tag_index(project_root)
    names = index.get(tag, [])
    results = []
    for n in names:
        m = load_memory_by_name(n, project_root)
        if m:
            results.append(m)
    return results


def search_by_type(mem_type: str, project_root: str = ".") -> list[TaggedMemory]:
    """按 type 检索。"""
    return [m for m in load_all_memories(project_root) if m.type == mem_type]


def search_by_daterange(start: Optional[str], end: Optional[str],
                        tag: Optional[str] = None, project_root: str = ".") -> list[TaggedMemory]:
    """按日期区间检索（优先 segtree 的双剪枝，降级为全量扫描）。"""
    s = _parse_date(start) if start else None
    e = _parse_date(end) if end else None
    tree = get_tree(project_root)
    if tree is not None:
        from datetime import date as _date
        lo = s or _date.min
        hi = e or _date.max
        names = tree.query_by_daterange(lo, hi, tag=tag, max_results=99999)
        results = [load_memory_by_name(n, project_root) for n in names]
        return [m for m in results if m is not None]

    # 降级：全量扫描
    result: list[TaggedMemory] = []
    for m in load_all_memories(project_root):
        if tag and tag not in m.tags:
            continue
        d = _parse_date(m.created_at)
        if s and d < s:
            continue
        if e and d > e:
            continue
        result.append(m)
    return result


def search(query: str, project_root: str = ".") -> list[TaggedMemory]:
    """混合检索：关键词（segtree/扫描）+ 向量语义召回（memory_vector）。

    关键词优先（精确匹配），向量补召回（语义相近但无关键词命中）。
    """
    # 1. 关键词检索（现有逻辑）
    keyword_hits: list[TaggedMemory] = []
    tree = get_tree(project_root)
    if tree is not None:
        names = tree.fuzzy_search(query)
        keyword_hits = [load_memory_by_name(n, project_root) for n in names]
        keyword_hits = [m for m in keyword_hits if m is not None]
    else:
        q = query.lower()
        for m in load_all_memories(project_root):
            haystack = " ".join([
                m.name, m.description, " ".join(m.tags), m.content,
            ]).lower()
            if q in haystack:
                keyword_hits.append(m)

    # 2. 向量语义召回（新增）——补关键词没命中的
    semantic_hits: list[TaggedMemory] = []
    try:
        from mai_agent.services.memory_vector import semantic_search
        semantic_hits = semantic_search(query, project_root)
    except Exception:
        pass  # 向量不可用则纯关键词

    # 3. 合并去重：关键词优先，语义补缺
    seen = {m.name for m in keyword_hits}
    for m in semantic_hits:
        if m.name not in seen:
            keyword_hits.append(m)
            seen.add(m.name)
    return keyword_hits


def all_tags(project_root: str = ".") -> list[str]:
    """所有已使用的标签。"""
    return sorted(load_tag_index(project_root).keys())


# ── Wiki-link 解析 ────────────────────────────────────────


def resolve_wikilinks(text: str, project_root: str = ".") -> str:
    """将文本中的 [[name]] 解析为对应记忆的摘要内联展开。

    用于把 SESSION_MEMORY.md 或对话中的 wiki-link 渲染为可读上下文。
    未找到的 link 保留原样（标记为待写）。
    """
    def _replace(match: re.Match) -> str:
        name = match.group(1).strip()
        m = load_memory_by_name(name, project_root)
        if m:
            return f"[{m.name}: {m.description}]"
        return f"[[{name}]]"  # 未关联，保留

    return _WIKILINK_RE.sub(_replace, text)


def related_memories(name: str, project_root: str = ".") -> list[TaggedMemory]:
    """返回 name 这条记忆通过 [[wiki-link]] 引用的、以及反向引用它的记忆。"""
    m = load_memory_by_name(name, project_root)
    if not m:
        return []
    outgoing = set(m.wiki_links())
    related = []
    for other in load_all_memories(project_root):
        if other.name == name:
            continue
        if other.name in outgoing or name in other.wiki_links():
            related.append(other)
    return related


# ── Prompt 注入 ───────────────────────────────────────────


def tagged_memory_context(project_root: str = ".", max_items: int = 30) -> str:
    """构建注入 system prompt 的标签化记忆上下文块。

    优先用 segtree 根摘要（~50 tokens），树不可用时降级为全量索引。
    放在 system prompt 末尾以保持前缀稳定（KV Cache 友好）。
    """
    # 优先 segtree
    tree = get_tree(project_root)
    if tree is not None and tree.root is not None:
        root = tree.root
        # 注入前兜底：summary 为空时用模板拼接补齐（无 LLM、确定性、仅内存操作），
        # 保证「共 N 条记忆 + 概览」永不空。LLM 版摘要合并（summarize_dirty_background）
        # 保持为可选增强，不自动触发（避免每轮 submit 产生 LLM 开销 + 与模板兜底抢 dirty）。
        if not root.summary and root.card_count > 0:
            try:
                tree.force_summarize_all()
            except Exception:
                pass
        lines = ["[Memory — 用 MemorySearch 按需获取详情]"]
        lines.append(f"共 {root.card_count} 条记忆。{root.summary}" if root.summary
                     else f"共 {root.card_count} 条记忆。")

        # 活跃主题
        recent = tree.recent_topics(months=3, max_topics=8)
        if recent:
            lines.append(f"近期主题: {', '.join(recent)}")
        lines.append("[End Memory]")
        return "\n".join(lines)

    # 降级：全量索引
    memories = load_all_memories(project_root)
    if not memories:
        return ""
    lines = ["[Tagged Memories — 长期记忆卡片索引，可用 [[name]] 引用]"]
    for m in sorted(memories, key=lambda x: x.name)[:max_items]:
        tags = f" #{' #'.join(m.tags)}" if m.tags else ""
        lines.append(f"- [[{m.name}]] ({m.type}){tags} — {m.description}")
    tags = all_tags(project_root)
    if tags:
        lines.append(f"可用标签: {', '.join(tags)}")
    lines.append("[End Tagged Memories]")
    return "\n".join(lines)
