"""知识库灌库脚本 — 把本地笔记灌进 MAI-agent 的混合检索知识库。

用法: python -X utf8 eval/seed_knowledge.py

数据源（选择性收录，见 SELECT_DIRS / EXCLUDE）:
  - 面经题库、八股笔记 = 用户的"知识边界"语料（概念边界检测的判定基准）
  - 排除 clown-src-6k-skill（第三方 SRC 安全知识库，非本人知识，灌进去会污染边界）

切分: 按 markdown 标题（#/##）切段，文件名作前缀保留上下文；无标题文件整篇一段。
向量: bge-m3 本地模型（1024 维，与现有 chroma 集合维度一致）。
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mai_agent.knowledge.vector_store import get_store
from mai_agent.knowledge.embedding import create_embedding

NOTES_ROOT = Path(r"D:\知识点总结\学习")
STORE_DIR = str(Path(__file__).parent.parent / ".mai" / "chroma")

# 收录范围：面经题库 + deep learn 顶层笔记 + 比赛补题笔记
SELECT = [
    NOTES_ROOT / "deep learn" / "面经题库",
    NOTES_ROOT / "deep learn",
    NOTES_ROOT / "PRJ",
]
# 排除：第三方安全知识库 / 依赖目录 / 题库目录已在 SELECT[0] 覆盖避免重复
EXCLUDE_PARTS = {"clown-src-6k-skill", "node_modules", ".pnpm-tool"}


def collect_files() -> list[Path]:
    files: set[Path] = set()
    for base in SELECT:
        if not base.exists():
            continue
        for f in base.rglob("*.md"):
            if any(part in EXCLUDE_PARTS for part in f.parts):
                continue
            # deep learn 顶层只要直属文件（面经题库子目录已由 SELECT[0] 覆盖，set 去重即可）
            files.add(f)
    return sorted(files)


def split_sections(text: str) -> list[tuple[str, str]]:
    """按 # / ## 标题切分 → [(section_title, body)]。无标题返回整篇。"""
    parts = re.split(r"(?m)^(#{1,2}\s+.+)$", text)
    sections: list[tuple[str, str]] = []
    if parts[0].strip():
        sections.append(("(开头)", parts[0].strip()))
    for i in range(1, len(parts), 2):
        title = parts[i].lstrip("#").strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if body:
            sections.append((title, body))
    return sections or [("(整篇)", text.strip())]


async def main() -> None:
    files = collect_files()
    print(f"收录文件: {len(files)} 个")

    # bge-large-zh-v1.5：本地缓存完整、1024 维与 chroma 集合一致。
    # 缓存的 snapshot 目录名（1024d）不是合法 commit hash，hub 按名字解析会
    # 试图联网 → SSL 失败，所以直接指到快照路径绕过 hub 解析。
    model_path = str(
        Path.home() / ".cache/huggingface/hub/models--BAAI--bge-large-zh-v1.5/snapshots/1024d"
    )
    embedding = create_embedding("local", model_name=model_path)
    store = get_store(STORE_DIR, embedding_backend=embedding)

    before = await store.count()
    n_chunks = 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(NOTES_ROOT)
        for idx, (title, body) in enumerate(split_sections(text)):
            # 段前加来源前缀：检索时标题命中也是信号
            doc_text = f"{rel} — {title}\n\n{body}"
            doc_id = f"{rel}#{idx}"
            await store.add(doc_id, doc_text, metadata={
                "source": str(rel), "section": title, "type": "notes",
            })
            n_chunks += 1
        print(f"  {rel} → {len(split_sections(text))} 段")

    after = await store.count()
    print(f"\n完成: {before} → {after} 条（新增 {n_chunks} 段）")

    # 冒烟验证：面经式提问能否命中对应笔记
    for q in ["Redis 分布式锁怎么实现", "MySQL 索引为什么用 B+ 树", "线程池参数怎么配"]:
        results = await store.search(q, top_k=3)
        print(f"\nQ: {q}")
        for r in results:
            print(f"  [{r['score']:.3f}] {r['metadata'].get('source', '?')} / {r['metadata'].get('section', '?')}"
                  f"  (vec={r['sources']['vector']:.2f} bm25={r['sources']['bm25']:.2f})")


if __name__ == "__main__":
    asyncio.run(main())
